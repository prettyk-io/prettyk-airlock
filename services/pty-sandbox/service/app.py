# -*- coding: utf-8 -*-
"""PTY-SANDBOX-1: ephemeral-контейнер на сессию — lifecycle API для cosmo-api.

Границы (COS-189 §4-5, дизайн PTY-контура; канон Web IDE THREAT-MODEL):
  - сервис владеет docker.sock и создаёт ОДНОРАЗОВЫЙ контейнер на сессию из
    образа с allowlist-инструментами; вход — только tool из allowlist
    (не free-shell: entrypoint образа — /usr/local/bin/sandbox-run);
  - профиль изоляции §5: non-root, cap-drop ALL, no-new-privileges, read-only
    rootfs + tmpfs (/workspace, /tmp), network none, лимиты cpu/mem/pids,
    TTL idle+hard, kill; без host-mount'ов и docker.sock внутри сессии;
  - внутренняя граница для cosmo-api: create/stop/status/touch;
    аудит open/close/exit/deny — JSONL на volume (для session manager'а);
  - default-off: сервис — compose-профиль ``pty`` (без него не поднимается).

Эндпоинты (внутренние, cosmo-net):
  POST   /sessions             создать сессию
  GET    /sessions             список
  GET    /sessions/{id}        статус
  DELETE /sessions/{id}        остановить (status=stopped)
  POST   /sessions/{id}/touch  обновить idle-активность (шов PTY-SERVER-2)
  GET    /sessions/{id}/attach     attach stdout: HTTP-chunked сырой PTY-поток (1.1)
  POST   /sessions/{id}/stdin      attach stdin: chunked body -> stdin процесса (1.1)
  POST   /sessions/{id}/resize     PTY-resize rows/cols (1.1)
  POST   /sessions/{id}/workspace  доставка tar-архива в /workspace (read-only, 1.1)
  GET    /health
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from logic import (
    clamp_resize,
    clamp_ttl,
    parse_allowlist,
    sanitize_delivery_tar,
    session_labels,
    validate_args,
    validate_id_field,
    validate_tool,
)

# ── Конфиг (env) ─────────────────────────────────────────────────────────

IMAGE = os.getenv("PTY_SANDBOX_IMAGE", "pty-sandbox-base:local")
IDLE_TTL_S = int(os.getenv("PTY_SANDBOX_IDLE_TTL_S", "900"))
HARD_TTL_S = int(os.getenv("PTY_SANDBOX_HARD_TTL_S", "3600"))
MAX_TTL_S = int(os.getenv("PTY_SANDBOX_MAX_TTL_S", str(HARD_TTL_S)))
MAX_SESSIONS = int(os.getenv("PTY_SANDBOX_MAX_SESSIONS", "4"))
ALLOWLIST = parse_allowlist(os.getenv(
    "PTY_SANDBOX_ALLOWLIST", "git,ls,cat,grep,find,head,tail,wc"))
AUDIT_LOG = os.getenv("PTY_SANDBOX_AUDIT_LOG", "/var/log/pty-sandbox/audit.jsonl")
REAP_INTERVAL_S = float(os.getenv("PTY_SANDBOX_REAP_INTERVAL_S", "5"))

# Профиль изоляции §5: лимиты сессии.
MEM_LIMIT = os.getenv("PTY_SANDBOX_MEM_LIMIT", "256m")
PIDS_LIMIT = int(os.getenv("PTY_SANDBOX_PIDS_LIMIT", "128"))
CPU_LIMIT = float(os.getenv("PTY_SANDBOX_CPU_LIMIT", "1.0"))
WORKSPACE_MB = int(os.getenv("PTY_SANDBOX_WORKSPACE_MB", "64"))
TMP_MB = int(os.getenv("PTY_SANDBOX_TMP_MB", "16"))
SANDBOX_USER = os.getenv("PTY_SANDBOX_USER", "sandbox")

# 1.1: attach-шов + доставка workspace.
ATTACH_CHUNK = int(os.getenv("PTY_SANDBOX_ATTACH_CHUNK", "65536"))
MAX_DELIVERY_MB = int(os.getenv("PTY_SANDBOX_MAX_DELIVERY_MB", "32"))
MAX_DELIVERY_ENTRIES = int(os.getenv("PTY_SANDBOX_MAX_DELIVERY_FILES", "2000"))
MAX_UNPACKED_MB = int(os.getenv("PTY_SANDBOX_MAX_UNPACKED_MB", "48"))
DEBUG = os.getenv("PTY_SANDBOX_DEBUG", "").strip() == "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] pty-sandbox: %(message)s",
)
log = logging.getLogger("pty-sandbox")

# ── Аудит (JSONL на volume; без silent exec) ─────────────────────────────

_audit_lock = threading.Lock()


def audit(event: str, **fields: object) -> None:
    """Запись события аудита: open/close/exit/deny/limits (JSONL + stdout)."""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "event": event,
        **fields,
    }
    line = json.dumps(rec, ensure_ascii=False)
    with _audit_lock:
        try:
            parent = os.path.dirname(AUDIT_LOG)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:  # noqa: BLE001 — аудит не должен ронять сервис
            log.warning("audit write failed: %s", exc)
    log.info("audit %s", line)


# ── Сессии ───────────────────────────────────────────────────────────────

@dataclass
class Session:
    id: str
    run_id: str
    principal: str
    repo: str
    commit_sha: str
    tool: str
    args: list = field(default_factory=list)
    container_id: str = ""
    created_at: float = 0.0
    last_activity: float = 0.0
    ttl_s: int = 0
    status: str = "running"          # running | exited | stopped | killed
    exit_code: Optional[int] = None
    kill_reason: str = ""
    workspace_delivery: Optional[dict] = None


SESSIONS: dict[str, Session] = {}

_docker = None


def docker_client():
    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker


def _container(sess: Session):
    try:
        return docker_client().containers.get(sess.container_id)
    except NotFound:
        return None


def _refresh_state(sess: Session, container) -> None:
    """Обновить статус по docker-состоянию; audit session_exit один раз."""
    if sess.status in ("stopped", "killed"):
        return
    try:
        container.reload()
    except DockerException:
        return
    if container.status == "exited":
        if sess.status != "exited":
            sess.status = "exited"
            sess.exit_code = int((container.attrs.get("State") or {}).get("ExitCode", 0))
            audit("session_exit", session_id=sess.id, run_id=sess.run_id,
                  exit_code=sess.exit_code, tool=sess.tool)


def _kill(sess: Session, reason: str, *, final_status: str = "killed") -> None:
    """Остановить и удалить контейнер сессии; записать аудит."""
    container = _container(sess)
    if container is not None:
        try:
            container.stop(timeout=3)
        except DockerException:
            pass
        try:
            container.remove(force=True)
        except DockerException:
            pass
    sess.status = final_status
    sess.kill_reason = reason
    audit("session_kill", session_id=sess.id, run_id=sess.run_id,
          reason=reason, final_status=final_status, tool=sess.tool)


def session_view(s: Session) -> dict:
    return {
        "session_id": s.id,
        "run_id": s.run_id,
        "principal": s.principal,
        "repo": s.repo,
        "commit_sha": s.commit_sha,
        "tool": s.tool,
        "args": s.args,
        "container_id": s.container_id,
        "status": s.status,
        "exit_code": s.exit_code,
        "kill_reason": s.kill_reason,
        "workspace_delivery": s.workspace_delivery,
        "created_at": s.created_at,
        "last_activity": s.last_activity,
        "ttl_s": s.ttl_s,
        "idle_ttl_s": IDLE_TTL_S,
    }


# ── API ──────────────────────────────────────────────────────────────────

app = FastAPI(title="cosmo-pty-sandbox", version="0.1.0")


class CreateSessionRequest(BaseModel):
    run_id: str
    principal: str
    repo: str
    tool: str
    commit_sha: str = ""
    args: list[str] = Field(default_factory=list)
    ttl_s: Optional[int] = None


@app.post("/sessions", status_code=201)
async def create_session(body: CreateSessionRequest) -> dict:
    if not ALLOWLIST:
        raise HTTPException(status_code=503,
                            detail="pty sandbox allowlist is not configured")
    try:
        run_id = validate_id_field(body.run_id, "run_id")
        principal = validate_id_field(body.principal, "principal")
        repo = validate_id_field(body.repo, "repo")
        tool = validate_id_field(body.tool, "tool")
        commit_sha = str(body.commit_sha or "").strip()
        if commit_sha:
            commit_sha = validate_id_field(commit_sha, "commit_sha")
        args = validate_args(body.args)
        ttl_s = clamp_ttl(body.ttl_s, HARD_TTL_S, MAX_TTL_S)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not validate_tool(tool, ALLOWLIST):
        audit("session_denied", run_id=run_id, principal=principal,
              tool=tool, reason="allowlist")
        raise HTTPException(status_code=403,
                            detail=f"tool '{tool}' is not in allowlist")

    running = [s for s in SESSIONS.values() if s.status == "running"]
    if len(running) >= MAX_SESSIONS:
        audit("session_denied", run_id=run_id, principal=principal,
              reason="max_sessions", active=len(running))
        raise HTTPException(status_code=429,
                            detail=f"max sessions reached ({MAX_SESSIONS})")

    sid = uuid.uuid4().hex[:16]

    def _run_container():
        return docker_client().containers.run(
            image=IMAGE,
            command=[tool, *args],
            name=f"pty-sess-{sid}",
            user=SANDBOX_USER,
            working_dir="/workspace",
            read_only=True,
            tmpfs={
                # 1.1: /workspace read-only для процесса (доставленный код RO);
                # скретч сессии — /tmp.
                "/workspace": f"rw,size={WORKSPACE_MB}m,mode=755",
                "/tmp": f"rw,size={TMP_MB}m,mode=1777",
            },
            network_mode="none",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=MEM_LIMIT,
            pids_limit=PIDS_LIMIT,
            nano_cpus=int(CPU_LIMIT * 1_000_000_000),
            labels=session_labels(sid, run_id),
            detach=True,
            tty=True,
            stdin_open=True,
            environment={"HOME": "/tmp"},
        )

    try:
        container = await asyncio.to_thread(_run_container)
    except ImageNotFound as exc:
        audit("session_denied", run_id=run_id, principal=principal,
              reason="image_missing", image=IMAGE)
        raise HTTPException(status_code=503,
                            detail=f"sandbox image not available: {IMAGE}") from exc
    except DockerException as exc:
        audit("session_denied", run_id=run_id, principal=principal,
              reason="docker_error", error=str(exc)[:200])
        raise HTTPException(status_code=503,
                            detail=f"docker error: {type(exc).__name__}") from exc

    now = time.time()
    sess = Session(
        id=sid, run_id=run_id, principal=principal, repo=repo,
        commit_sha=commit_sha, tool=tool, args=args,
        container_id=container.id, created_at=now, last_activity=now,
        ttl_s=ttl_s,
    )
    SESSIONS[sid] = sess
    audit("session_create", session_id=sid, run_id=run_id, principal=principal,
          repo=repo, commit_sha=commit_sha, tool=tool, container_id=container.id,
          ttl_s=ttl_s)
    return session_view(sess)


@app.get("/sessions")
async def list_sessions() -> dict:
    return {"sessions": [session_view(s) for s in SESSIONS.values()],
            "max_sessions": MAX_SESSIONS}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    sess = SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status not in ("stopped", "killed"):
        container = await asyncio.to_thread(_container, sess)
        if container is not None:
            await asyncio.to_thread(_refresh_state, sess, container)
    return session_view(sess)


@app.delete("/sessions/{session_id}")
async def stop_session(session_id: str) -> dict:
    sess = SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status == "running":
        await asyncio.to_thread(_kill, sess, "requested", final_status="stopped")
    return session_view(sess)


@app.post("/sessions/{session_id}/touch")
async def touch_session(session_id: str) -> dict:
    """Шов PTY-SERVER-2: ввод/активность продлевают idle-TTL."""
    sess = SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    sess.last_activity = time.time()
    return {"session_id": sess.id, "last_activity": sess.last_activity,
            "idle_ttl_s": IDLE_TTL_S}


# ── Attach-шов (PTY-SANDBOX-1.1): HTTP-chunked ───────────────────────────
#
# Решение 1.1 — HTTP-chunked (не WS): нулевые новые зависимости на обеих
# сторонах (Starlette out; httpx у cosmo-api), зеркалит модель «SSE (out) +
# POST (in)» дизайна COS-189. out: GET /attach — сырые октеты PTY; in:
# POST /stdin — chunked body; resize — JSON; exit-code — GET /sessions/{id}
# после конца out-потока (status/exit_code).

_stdin_active: dict[str, bool] = {}
_stdin_lock = threading.Lock()


def _open_attach_socket(sess: Session, params: dict):
    container = _container(sess)
    if container is None:
        raise DockerException("sandbox container not found")
    return container.attach_socket(params=params)


def _raw_sock(sock):
    """docker-py 7.2 отдаёт stdlib socket.SocketIO (rb-only, sticky-timeout:
    после таймаута read бросает 'cannot read from timed out object').
    Работаем с нижележащим сырым сокетом: recv/sendall без залипаний."""
    return getattr(sock, "_sock", None) or sock


def _sock_write(sock, data: bytes) -> None:
    raw = _raw_sock(sock)
    if hasattr(raw, "sendall"):
        raw.sendall(data)
        return
    view = memoryview(data)
    while view:
        sent = sock.write(view)
        if not sent:
            raise OSError("attach stdin write returned 0")
        view = view[sent:]


def _read_chunk(sock) -> Optional[bytes]:
    """Прочитать чанк PTY; None — таймаут (для disconnect-полла); b'' — EOF."""
    raw = _raw_sock(sock)
    try:
        if hasattr(raw, "recv"):
            return raw.recv(ATTACH_CHUNK)
        return sock.read(ATTACH_CHUNK)
    except TimeoutError:
        return None
    except (OSError, ValueError):
        return b""


def _exec_with_stdin(container, argv: list, data: bytes, *,
                     user: str = "root", timeout_s: float = 120.0) -> None:
    """Выполнить команду в контейнере, скормив data в stdin (hijack; 7.2: raw sendall).

    Команда обязана завершиться сама (напр. `head -c N`): закрытие hijack-сокета
    EOF процессу не доставляет (проверено на docker 7.2). Успех = Running=False,
    ExitCode=0; иначе DockerException.
    """
    api = container.client.api
    exec_id = api.exec_create(container.id, argv, user=user, stdin=True)["Id"]
    resp = api.exec_start(exec_id, socket=True)
    try:
        _raw_sock(resp).sendall(data)
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        info = api.exec_inspect(exec_id)
        if not info.get("Running"):
            code = info.get("ExitCode")
            if code is None:
                time.sleep(0.2)
                code = api.exec_inspect(exec_id).get("ExitCode")
            if int(code or 0) != 0:
                raise DockerException(f"exec failed rc={code}")
            return
        time.sleep(0.15)
    raise DockerException("exec did not finish in time")


class ResizeRequest(BaseModel):
    rows: int
    cols: int


@app.get("/sessions/{session_id}/attach")
async def session_attach(session_id: str, request: Request):
    """Attach stdout: сырой PTY-поток (octet-stream, chunked, live-only)."""
    sess = SESSIONS.get(session_id)
    if sess is None:
        audit("attach_denied", session_id=session_id, reason="not_found")
        raise HTTPException(status_code=404, detail="session not found")
    container = await asyncio.to_thread(_container, sess)
    if container is not None:
        await asyncio.to_thread(_refresh_state, sess, container)
    if sess.status != "running":
        audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
              reason="not_running", status=sess.status)
        raise HTTPException(status_code=409, detail={
            "status": sess.status, "exit_code": sess.exit_code})
    try:
        sock = await asyncio.to_thread(
            _open_attach_socket, sess,
            {"stdout": 1, "stderr": 1, "stream": 1, "logs": 0})
    except DockerException as exc:
        audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
              reason="attach_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503,
                            detail=f"attach failed: {type(exc).__name__}") from exc

    raw_sock = _raw_sock(sock)
    try:
        raw_sock.settimeout(0.5)  # тик для disconnect-полла
    except OSError:
        pass
    audit("attach_open", session_id=sess.id, run_id=sess.run_id,
          tool=sess.tool, transport="http-chunked")

    async def _stream():
        reason = "detached"
        try:
            while True:
                chunk = await asyncio.to_thread(_read_chunk, sock)
                if DEBUG:
                    log.info("dbg attach read: %r",
                             chunk[:60] if isinstance(chunk, (bytes, bytearray))
                             else chunk)
                if chunk is None:
                    try:
                        gone = await request.is_disconnected()
                    except Exception:  # noqa: BLE001
                        gone = False
                    if gone:
                        reason = "client_disconnect"
                        break
                    continue
                if not chunk:
                    reason = "stream_end"
                    break
                sess.last_activity = time.time()
                yield chunk
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                cont = _container(sess)
                if cont is not None:
                    _refresh_state(sess, cont)
                if sess.status == "exited":
                    reason = "process_exit"
            except Exception:  # noqa: BLE001
                pass
            audit("attach_close", session_id=sess.id, run_id=sess.run_id,
                  reason=reason)

    return StreamingResponse(_stream(), media_type="application/octet-stream")


@app.post("/sessions/{session_id}/stdin", status_code=204)
async def session_stdin(session_id: str, request: Request):
    """Attach stdin: chunked body стримится в stdin процесса (конец тела = detach канала)."""
    sess = SESSIONS.get(session_id)
    if sess is None:
        audit("attach_denied", session_id=session_id, reason="not_found")
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status != "running":
        audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
              reason="not_running", status=sess.status)
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")
    try:
        sock = await asyncio.to_thread(
            _open_attach_socket, sess, {"stdin": 1, "stream": 1, "logs": 0})
    except DockerException as exc:
        audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
              reason="stdin_open_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503,
                            detail=f"attach failed: {type(exc).__name__}") from exc

    with _stdin_lock:
        if _stdin_active.get(session_id):
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
                  reason="stdin_busy")
            raise HTTPException(status_code=409,
                                detail="stdin stream already active")
        _stdin_active[session_id] = True
    audit("attach_stdin_open", session_id=sess.id, run_id=sess.run_id,
          tool=sess.tool)
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            if DEBUG:
                log.info("dbg stdin write: %d bytes", len(chunk))
            await asyncio.to_thread(_sock_write, sock, chunk)
            sess.last_activity = time.time()
    except ClientDisconnect:
        pass
    except (DockerException, OSError) as exc:
        log.info("stdin stream ended: %s", type(exc).__name__)
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass
        with _stdin_lock:
            _stdin_active.pop(session_id, None)
        audit("attach_stdin_close", session_id=sess.id, run_id=sess.run_id)
    return Response(status_code=204)


@app.post("/sessions/{session_id}/resize")
async def session_resize(session_id: str, body: ResizeRequest) -> dict:
    sess = SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status != "running":
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")
    try:
        rows, cols = clamp_resize(body.rows, body.cols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    container = await asyncio.to_thread(_container, sess)
    if container is None:
        raise HTTPException(status_code=409,
                            detail="sandbox container not found")
    try:
        await asyncio.to_thread(container.resize, rows, cols)
    except DockerException as exc:
        audit("attach_denied", session_id=sess.id, run_id=sess.run_id,
              reason="resize_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503,
                            detail=f"resize failed: {type(exc).__name__}") from exc
    sess.last_activity = time.time()
    return {"session_id": sess.id, "rows": rows, "cols": cols}


@app.post("/sessions/{session_id}/workspace", status_code=201)
async def deliver_workspace(session_id: str, request: Request) -> dict:
    """Доставка checkout: raw tar -> санитайз -> /workspace (RO для процесса)."""
    sess = SESSIONS.get(session_id)
    if sess is None:
        audit("delivery_denied", session_id=session_id, reason="not_found")
        raise HTTPException(status_code=404, detail="session not found")
    if sess.status != "running":
        audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
              reason="not_running", status=sess.status)
        raise HTTPException(status_code=409, detail=f"session is {sess.status}")

    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ("application/x-tar", "application/tar",
                     "application/octet-stream"):
        audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
              reason="bad_content_type", content_type=ctype[:64])
        raise HTTPException(status_code=415,
                            detail=f"unsupported content-type: {ctype or 'none'}")

    cap = MAX_DELIVERY_MB * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > cap:
                audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
                      reason="oversize", declared_bytes=int(declared),
                      cap_bytes=cap)
                raise HTTPException(
                    status_code=413,
                    detail=f"archive too large (max {MAX_DELIVERY_MB}MB)")
        except ValueError:
            pass

    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
                  reason="oversize", bytes=len(body), cap_bytes=cap)
            raise HTTPException(
                status_code=413,
                detail=f"archive too large (max {MAX_DELIVERY_MB}MB)")

    clean, reason, stats = sanitize_delivery_tar(
        bytes(body), max_entries=MAX_DELIVERY_ENTRIES,
        max_unpacked_bytes=MAX_UNPACKED_MB * 1024 * 1024)
    if clean is None:
        audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
              reason=reason, bytes=len(body))
        raise HTTPException(status_code=400,
                            detail=f"archive rejected: {reason}")

    container = await asyncio.to_thread(_container, sess)
    if container is None:
        audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
              reason="container_not_found")
        raise HTTPException(status_code=409,
                            detail="sandbox container not found")

    def _apply() -> None:
        wipe = container.exec_run(
            ["find", "/workspace", "-mindepth", "1", "-delete"], user="root")
        if wipe.exit_code != 0:
            raise DockerException(f"workspace wipe failed rc={wipe.exit_code}")
        # ro-rootfs блокирует put_archive (daemon: "rootfs is marked read-only"),
        # поэтому раскладка через exec: `head -c N | tar -x` — head читает ровно
        # N байт и завершается сам (без опоры на socket-EOF).
        cmd = f"head -c {len(clean)} | tar -xf - -C /workspace"
        _exec_with_stdin(container, ["sh", "-c", cmd], clean)

    try:
        await asyncio.to_thread(_apply)
    except DockerException as exc:
        audit("delivery_denied", session_id=sess.id, run_id=sess.run_id,
              reason="apply_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503,
                            detail=f"delivery failed: {type(exc).__name__}") from exc

    delivered_at = time.time()
    sess.workspace_delivery = {
        "files": stats["files"],
        "dirs": stats["dirs"],
        "bytes": stats["bytes"],
        "delivered_at": delivered_at,
    }
    sess.last_activity = delivered_at
    audit("delivery_ok", session_id=sess.id, run_id=sess.run_id,
          files=stats["files"], dirs=stats["dirs"], bytes=stats["bytes"])
    return {"session_id": sess.id, **sess.workspace_delivery}


@app.get("/health")
async def health() -> dict:
    running = sum(1 for s in SESSIONS.values() if s.status == "running")
    return {
        "ok": True,
        "image": IMAGE,
        "allowlist": list(ALLOWLIST),
        "idle_ttl_s": IDLE_TTL_S,
        "hard_ttl_s": HARD_TTL_S,
        "max_sessions": MAX_SESSIONS,
        "attach_chunk": ATTACH_CHUNK,
        "max_delivery_mb": MAX_DELIVERY_MB,
        "max_unpacked_mb": MAX_UNPACKED_MB,
        "sessions": {"running": running, "total": len(SESSIONS)},
    }


# ── Reaper: idle/hard TTL, refresh exited ────────────────────────────────

async def _reap_once() -> None:
    now = time.time()
    for sess in list(SESSIONS.values()):
        if sess.status in ("stopped", "killed"):
            continue
        container = await asyncio.to_thread(_container, sess)
        if container is not None:
            await asyncio.to_thread(_refresh_state, sess, container)
        if sess.status != "running":
            continue
        if now - sess.last_activity > IDLE_TTL_S:
            await asyncio.to_thread(_kill, sess, "idle_ttl")
        elif now - sess.created_at > sess.ttl_s:
            await asyncio.to_thread(_kill, sess, "hard_ttl")


async def _reaper_loop() -> None:
    while True:
        await asyncio.sleep(REAP_INTERVAL_S)
        try:
            await _reap_once()
        except Exception:  # noqa: BLE001 — фоновая уборка не роняет сервис
            log.exception("reaper tick failed")


@app.on_event("startup")
async def _startup() -> None:
    log.info(
        "starting: image=%s allowlist=%s idle_ttl=%ss hard_ttl=%ss max_sessions=%s",
        IMAGE, ",".join(ALLOWLIST), IDLE_TTL_S, HARD_TTL_S, MAX_SESSIONS,
    )
    try:
        await asyncio.to_thread(lambda: docker_client().images.get(IMAGE))
        log.info("sandbox image present: %s", IMAGE)
    except ImageNotFound:
        log.warning(
            "sandbox image MISSING: %s — build: docker build -t %s "
            "services/pty-sandbox/image", IMAGE, IMAGE,
        )
    except DockerException as exc:
        log.error("docker not reachable: %s", exc)
    asyncio.create_task(_reaper_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    for sess in list(SESSIONS.values()):
        if sess.status == "running":
            await asyncio.to_thread(_kill, sess, "service_shutdown")
    log.info("stopped")
