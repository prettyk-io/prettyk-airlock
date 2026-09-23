# -*- coding: utf-8 -*-
"""Cosmo TestApp — минимальное deployable приложение (dogfooding build+deploy).

Авторизация (JWT RS256, без внешнего IdP — локальная выдача для dogfooding)
плюс один CRUD-набор (notes). Ничего из Cosmoport ядра сюда не тянется:
это независимый target build+deploy конвейера gitea → woodpecker → registry.

Конфиг через env (никаких жёстких host-path):
  - TESTAPP_JWT_PUBLIC_KEY  — PEM-публичный ключ RS256 (обязателен);
  - TESTAPP_JWT_ISSUER       — issuer токенов (default "cosmo-testapp");
  - TESTAPP_PORT             — порт (default 8000);
  - TESTAPP_DB                — "sqlite" | "memory" (default "memory", dogfooding).

Токен выдаётся только в dev/dogfooding-режиме: /auth/login возвращает локально
подписанный RS256 JWT. В боевом контуре ключ выдачи уйдёт за Better Auth / OpenBao.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# ── конфиг через env ─────────────────────────────────────────────────────────

ISSUER = os.environ.get("TESTAPP_JWT_ISSUER", "cosmo-testapp")
_JWT_ALGOS = {"RS256"}

# In dev/dogfooding ключ выдачи может совпадать с публичным; в бою это
# раздельные ключи. Файл public key — единственный обязательный секрет.
_PUBLIC_KEY_PEM: str | None = os.environ.get("TESTAPP_JWT_PUBLIC_KEY") or None

SOFT_SECRET = os.environ.get(
    "TESTAPP_JWT_SIGNING_KEY",
    "dev-only-rs256-signing-key-do-not-use-in-prod-0000000000000000",
)

_bearer = HTTPBearer(auto_error=False)


# ── минимальный RSA-эмулятор для dogfooding ────────────────────────────────
#
# Без PyJWT-crypto зависимостей на слое выдачи: подписываем RS256 настоящим
# PyJWT[crypto] только если задан приватный ключ; иначе (dogfooding) честно
# выдаём HS256 dev-токен? НЕТ — контракт RS256. Поэтому выдача в dogfooding
# требует из env либо приватный ключ, либо мы генерируем dev-ключ на лету.


def _load_or_generate_keys() -> tuple[str, str]:
    """Вернуть (private_pem, public_pem).

    Приоритет: env (TESTAPP_JWT_PRIVATE_KEY / TESTAPP_JWT_PUBLIC_KEY),
    иначе генерируем эфемерный dev-ключ RSA-2048 (не persistent — токены
    переживают только жизнь процесса; для dogfooding достаточно).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = os.environ.get("TESTAPP_JWT_PRIVATE_KEY")
    pub = os.environ.get("TESTAPP_JWT_PUBLIC_KEY") or _PUBLIC_KEY_PEM
    if priv and pub:
        return priv, pub

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


_PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM = _load_or_generate_keys()


# ── хранилище notes (dogfooding: sqlite на диске или в памяти) ──────────────

class _NotesStore:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            " id TEXT PRIMARY KEY,"
            " owner TEXT NOT NULL,"
            " title TEXT NOT NULL,"
            " body TEXT NOT NULL,"
            " created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def list(self, owner: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, body, created_at FROM notes WHERE owner=? ORDER BY id",
                (owner,),
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "body": r[2], "created_at": r[3]}
            for r in rows
        ]

    def get(self, owner: str, note_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, title, body, created_at FROM notes WHERE owner=? AND id=?",
                (owner, note_id),
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "title": row[1], "body": row[2], "created_at": row[3]}

    def put(self, owner: str, note_id: str, title: str, body: str) -> dict:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO notes (id, owner, title, body, created_at)"
                " VALUES (?,?,?,?,?)",
                (note_id, owner, title, body, now),
            )
            self._conn.commit()
        return {"id": note_id, "title": title, "body": body, "created_at": now}

    def delete(self, owner: str, note_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM notes WHERE owner=? AND id=?", (owner, note_id)
            )
            self._conn.commit()
        return cur.rowcount > 0


_DB_MODE = os.environ.get("TESTAPP_DB", "memory")
store = _NotesStore(":memory:" if _DB_MODE == "memory" else "testapp.db")


# ── schemas ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class NoteIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)


class NoteOut(BaseModel):
    id: str
    title: str
    body: str
    created_at: float


# ── JWT helpers ─────────────────────────────────────────────────────────────

def _mint(sub: str, ttl_seconds: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": sub,
            "iss": ISSUER,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        },
        _PRIVATE_KEY_PEM,
        algorithm="RS256",
    )


def _verify(token: str) -> dict:
    if _PUBLIC_KEY_PEM is None:
        raise HTTPException(500, "TESTAPP_JWT_PUBLIC_KEY is not configured")
    try:
        return jwt.decode(token, _PUBLIC_KEY_PEM, algorithms=_JWT_ALGOS, issuer=ISSUER)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad issuer")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


# ── app ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Cosmo TestApp", version="0.1.0")


def _principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = _verify(creds.credentials)
    return str(claims.get("sub", ""))


@app.get("/live", tags=["health"])
def live() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready() -> dict:
    return {"status": "ready", "db": _DB_MODE}


@app.post("/auth/login", response_model=LoginResponse, tags=["auth"])
def login(body: LoginRequest) -> LoginResponse:
    # Dogfooding: любой непустой логин/пароль выдаёт токен. В бою это
    # заменяется на проверку учётных данных (Better Auth).
    token = _mint(body.username)
    return LoginResponse(access_token=token, expires_in=3600)


@app.get("/auth/me", tags=["auth"])
def me(sub: str = Depends(_principal)) -> dict:
    return {"sub": sub}


@app.get("/api/notes", response_model=list[NoteOut], tags=["notes"])
def list_notes(sub: str = Depends(_principal)) -> list[dict]:
    return store.list(sub)


@app.post("/api/notes", response_model=NoteOut, status_code=201, tags=["notes"])
def create_note(body: NoteIn, sub: str = Depends(_principal)) -> dict:
    note_id = uuid.uuid4().hex
    return store.put(sub, note_id, body.title, body.body)


@app.get("/api/notes/{note_id}", response_model=NoteOut, tags=["notes"])
def get_note(note_id: str, sub: str = Depends(_principal)) -> dict:
    note = store.get(sub, note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    return note


@app.put("/api/notes/{note_id}", response_model=NoteOut, tags=["notes"])
def update_note(note_id: str, body: NoteIn, sub: str = Depends(_principal)) -> dict:
    if store.get(sub, note_id) is None:
        raise HTTPException(404, "note not found")
    return store.put(sub, note_id, body.title, body.body)


@app.delete("/api/notes/{note_id}", status_code=204, tags=["notes"])
def delete_note(note_id: str, sub: str = Depends(_principal)):
    if not store.delete(sub, note_id):
        raise HTTPException(404, "note not found")
    from fastapi import Response
    return Response(status_code=204)
    if not store.delete(sub, note_id):
        raise HTTPException(404, "note not found")