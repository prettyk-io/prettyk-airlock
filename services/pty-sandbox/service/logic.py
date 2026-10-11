# -*- coding: utf-8 -*-
"""PTY-SANDBOX-1: чистая логика sandbox-сервиса (без внешних зависимостей).

Вынесено из app.py для тестов: allowlist, кламп TTL, валидация запроса.
Границы — COS-189 §4-5 (команд-скоупная сессия, не free-shell).
"""
from __future__ import annotations

import io
import re
import tarfile

#: Ограничения входа (защита от мусорных/гигантских запросов).
MAX_ARGS = 16
MAX_ARG_LEN = 256
MAX_ID_FIELD_LEN = 128
MAX_RUN_ID_LEN = 64
MAX_SESSION_ID_LEN = 64

#: Минимальный/максимальный per-session TTL (сек).
MIN_TTL_S = 5
MAX_TTL_S_CAP = 24 * 3600

#: Формат полей-идентификаторов (run_id/principal/repo/commit_sha): без пробелов
#: и управляющих символов; допускаем git-ref-подобные символы.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]*$")


def parse_allowlist(raw: str) -> tuple[str, ...]:
    """Разобрать comma-separated allowlist в нормализованный tuple.

    Пустые элементы игнорируются, дубликаты убираются, порядок сохраняется.
    Пустой итог = allowlist не сконфигурирован (сервис откажет в сессиях).
    """
    seen: dict[str, None] = {}
    for item in str(raw or "").split(","):
        item = item.strip()
        if item:
            seen.setdefault(item, None)
    return tuple(seen.keys())


def validate_tool(tool: str, allowlist: tuple[str, ...]) -> bool:
    """Инструмент обязан быть ОДНИМ элементом allowlist (не free-shell)."""
    return str(tool or "") in allowlist


def validate_args(args: object) -> list[str]:
    """Аргументы: список строк, разумной длины/количества; иначе ValueError.

    shell-инъекции здесь нет by construction (docker exec-команда — массив,
    без shell), но лимиты защищают от мусора и гигантских фреймов.
    """
    if args is None:
        return []
    if not isinstance(args, list):
        raise ValueError("args must be a list of strings")
    if len(args) > MAX_ARGS:
        raise ValueError(f"too many args (max {MAX_ARGS})")
    out: list[str] = []
    for item in args:
        s = str(item)
        if len(s) > MAX_ARG_LEN:
            raise ValueError(f"arg too long (max {MAX_ARG_LEN})")
        if "\x00" in s:
            raise ValueError("arg contains NUL")
        out.append(s)
    return out


def clamp_ttl(requested: object, default_ttl: int, max_ttl: int) -> int:
    """Per-session hard-TTL: int, кламп [MIN_TTL_S, min(max_ttl, MAX_TTL_S_CAP)].

    Без запроса — default_ttl (env сервиса), тоже клампнутый.
    """
    ceiling = max(MIN_TTL_S, min(int(max_ttl), MAX_TTL_S_CAP))
    if requested is None or requested == "":
        return max(MIN_TTL_S, min(int(default_ttl), ceiling))
    try:
        value = int(requested)
    except (TypeError, ValueError):
        raise ValueError("ttl_s must be an integer") from None
    return max(MIN_TTL_S, min(value, ceiling))


def validate_id_field(value: object, name: str) -> str:
    """Валидация идентификатора (run_id/principal/repo/commit_sha/tool)."""
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{name} is required")
    limit = MAX_RUN_ID_LEN if name == "run_id" else MAX_ID_FIELD_LEN
    if len(s) > limit:
        raise ValueError(f"{name} too long (max {limit})")
    if not _SAFE_ID_RE.match(s):
        raise ValueError(f"{name} has unsafe characters")
    return s


def session_labels(session_id: str, run_id: str) -> dict:
    """Docker-лейблы сессии (для диагностики/уборки)."""
    return {
        "cosmo.pty.session": session_id,
        "cosmo.pty.run_id": run_id,
        "managed-by": "pty-sandbox",
    }


# ── PTY-SANDBOX-1.1: attach-шов (resize) + доставка workspace ────────────

#: Границы PTY-resize (защита от мусора; клампим, не роняем).
RESIZE_ROWS_MAX = 500
RESIZE_COLS_MAX = 1000


def clamp_resize(rows: object, cols: object) -> tuple[int, int]:
    """Валидировать и клампнуть размер PTY.

    Нечисла и значения <= 0 — ValueError (422 у сервиса); слишком большие
    значения клампятся до RESIZE_ROWS_MAX/RESIZE_COLS_MAX.
    """
    def _one(value: object, name: str, hi: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer") from None
        if parsed <= 0:
            raise ValueError(f"{name} must be positive")
        return min(parsed, hi)

    return _one(rows, "rows", RESIZE_ROWS_MAX), _one(cols, "cols", RESIZE_COLS_MAX)


def normalize_relpath(name: object) -> str | None:
    """Нормализовать имя внутри tar-архива доставки; None — небезопасно.

    Отвергаем: пустое, NUL, абсолютные пути, Windows-разделители/диски,
    '..'/'.' и пустые сегменты. Ведущие './' снимаются, хвостовой '/'
    у директорий отбрасывается.
    """
    n = str(name or "")
    if not n or "\x00" in n:
        return None
    while n.startswith("./"):
        n = n[2:]
    n = n.rstrip("/")
    if not n or n.startswith("/") or "\\" in n or ":" in n:
        return None
    parts = n.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return "/".join(parts)


def sanitize_delivery_tar(
    raw: bytes,
    *,
    max_entries: int,
    max_unpacked_bytes: int,
) -> tuple[bytes | None, str, dict]:
    """Проверить и пересобрать tar доставки в безопасный канонический вид.

    Политика (fail-closed): только regular files и каталоги; относительные
    безопасные имена; все родительские каталоги достраиваются; владелец
    root:root, файлы 0644, каталоги 0755 — доставленный код read-only для
    процесса сессии (uid 1000).

    Returns: (clean_tar | None, reason, stats).
    reason: "" | bad_archive | unsafe_path | unsupported_entry |
            too_many_entries | too_large_unpacked.
    """
    stats = {"files": 0, "dirs": 0, "bytes": 0}
    try:
        src = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except (tarfile.TarError, ValueError, OSError):
        return None, "bad_archive", stats

    try:
        entries: dict[str, tuple[str, int, tarfile.TarInfo]] = {}
        dirs: set[str] = set()
        total = 0
        for member in src.getmembers():
            if len(entries) >= max_entries:
                return None, "too_many_entries", stats
            rel = normalize_relpath(member.name)
            if rel is None:
                return None, "unsafe_path", stats
            if member.isdir():
                dirs.add(rel)
                entries.setdefault(rel, ("d", 0, member))
                continue
            if not member.isfile():
                return None, "unsupported_entry", stats
            size = int(member.size or 0)
            total += size
            if total > max_unpacked_bytes:
                return None, "too_large_unpacked", stats
            if rel not in entries:
                stats["files"] += 1
            entries.setdefault(rel, ("f", size, member))

        # Родительские каталоги — явными DIRTYPE-записями.
        for rel in list(entries):
            parts = rel.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))

        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:") as dst:
            for d in sorted(dirs):
                ti = tarfile.TarInfo(name=d + "/")
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mtime = 0
                dst.addfile(ti)
            for rel in sorted(entries):
                kind, size, member = entries[rel]
                if kind != "f":
                    continue
                ti = tarfile.TarInfo(name=rel)
                ti.type = tarfile.REGTYPE
                ti.size = size
                ti.mode = 0o644
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mtime = 0
                dst.addfile(ti, src.extractfile(member))
        stats["dirs"] = len(dirs)
        stats["bytes"] = total
        return out.getvalue(), "", stats
    finally:
        src.close()

