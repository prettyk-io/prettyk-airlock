"""COS-088: SSE event backlog — reconnect без потери событий.

Проблема: SSE-стримы (runs/domains/notifications) до COS-088 не несли
event id, поэтому клиент не мог сказать серверу, с какого события он
ушёл (SSE Last-Event-ID), а рестарт cosmo-api стирал in-memory историю —
reconnect после рестарта не мог отличить «пропуск» от «тишины».

Решение: каждое стримовое событие дублируется в Valkey Stream
(``cosmo:sse:bl:{kind}:{key}``) с TTL и MAXLEN; SSE-событие получает тот
же id, что и запись в backlog (XADD id — монотонный по stream-ключу).
Клиент переподключается с ``Last-Event-ID`` (стандартный EventSource
заголовок) или ``last_event_id`` query-параметром (клиентский reconnect
создаёт НОВЫЙ EventSource — браузерный автозаголовок при ручном
reconnect не работает) и получает недоставленные события; если его
last-event-id больше не в backlog (TTL-вытеснение/триминг/пустой
stream) — это GAP: клиенту шлётся resync-снапшот, не тишина.

Деградация (never hard dependency, как COS-079): если valkey-клиент не
установлен или Valkey недоступен, работает in-memory ring (per-key
deque) — replay работает внутри процесса, но история НЕ переживает
рестарт (после рестарта любой reconnect с Last-Event-ID → gap → resync).
Режим наблюдаем: ответ содержит заголовок ``X-Cosmo-Backlog`` и первое
SSE-событие ``stream_backlog`` с полем mode ("valkey" | "memory").

Publish не дедуплицируется: одно и то же логическое событие может быть
записано двумя соединениями под разными id — повторы state-based событий
(SSE-клиенты идемпотентно обновляют state) безвредны, а отсутствие
read-before-write дедупа не ставит publish под гонку.

Ключевой инвариант: SSE id события == id записи в backlog. Соединение
yield'ит событие с тем же id, под которым оно лежит в backlog; resample
``after`` последнего полученного клиентом id тогда корректен.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

BACKLOG_TTL_S = 900          # sliding TTL на stream-ключ (обновляется при publish)
BACKLOG_MAXLEN = 2000        # верхняя граница записей на stream-ключ (valkey)
RING_MAXLEN = 500            # in-memory фолбэк
_KEY_PREFIX = "cosmo:sse:bl:"

_valkey_client: Optional[Any] = None
_valkey_mode_logged = False


def _valkey_url() -> str:
    url = os.getenv("COSMO_VALKEY_URL", "").strip()
    if url:
        return url
    host = os.getenv("PK_VALKEY_HOST", "localhost").strip() or "localhost"
    port = os.getenv("PK_VALKEY_PORT", "6379").strip() or "6379"
    return f"redis://{host}:{port}/0"


def _get_valkey() -> Optional[Any]:
    """Lazily connect valkey client; None если недоступен.

    Успех кэшируется на жизнь процесса; неудача НЕ кэшируется —
    следующий publish/replay повторит попытку (см. sse_tickets._get_valkey).
    """
    global _valkey_client, _valkey_mode_logged
    if _valkey_client is not None:
        return _valkey_client
    try:
        import valkey  # lazy — optional dependency, никогда не требуется при импорте
    except ImportError:
        if not _valkey_mode_logged:
            logger.warning(
                "[SSE:BACKLOG] valkey client library not installed — "
                "backlog falls back to in-process memory ring (history is "
                "NOT restart-proof; install valkey for durable backlog)"
            )
            _valkey_mode_logged = True
        return None
    try:
        client = valkey.Valkey.from_url(_valkey_url(), socket_connect_timeout=1.0)
        client.ping()
    except Exception:  # noqa: BLE001 — valkey down → memory fallback
        if not _valkey_mode_logged:
            logger.warning(
                "[SSE:BACKLOG] valkey unreachable at %s — "
                "backlog falls back to in-memory ring (history lost on restart)",
                _valkey_url(),
            )
            _valkey_mode_logged = True
        return None
    logger.info("[SSE:BACKLOG] event backlog enabled via valkey %s", _valkey_url())
    _valkey_client = client
    return client


def backlog_mode() -> str:
    """Наблюдаемый флаг деградации: 'valkey' или 'memory'.

    'memory' — валидный режим: replay работает внутри процесса; после
    рестарта API история недоступна (клиент получит gap → resync).
    """
    return "valkey" if _get_valkey() is not None else "memory"


def _stream_key(kind: str, key: str) -> str:
    return f"{_KEY_PREFIX}{kind}:{key}"


def _id_tuple(event_id: str) -> tuple[int, int]:
    """'<ms>-<seq>' → (ms, seq) для сравнения/сортировки."""
    ms, _, seq = event_id.partition("-")
    try:
        return (int(ms), int(seq or 0))
    except ValueError:
        return (0, 0)


def _dec(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


# ── in-memory ring (fallback, per-process; история умирает с процессом) ──

_rings: dict[str, deque] = {}
_counters: dict[str, int] = {}
_ring_lock = threading.Lock()


def _ring_add(stream: str, fields: dict[str, str]) -> str:
    ms = int(time.time() * 1000)
    with _ring_lock:
        seq = _counters.get(stream, 0) + 1
        _counters[stream] = seq
        event_id = f"{ms}-{seq}"
        ring = _rings.setdefault(stream, deque(maxlen=RING_MAXLEN))
        ring.append((event_id, dict(fields)))
        return event_id


def _ring_replay(stream: str, after_id: str, limit: int):
    ring = _rings.get(stream)
    if not ring:
        # Ring пуст: история отсутствует (рестарт процесса / вытеснение) —
        # если клиент называет last-event-id, непрерывность проверить нельзя.
        return [], True
    entries = list(ring)
    if any(eid == after_id for eid, _f in entries):
        records = [
            EventRecord(id=eid, event_type=f["t"], data=f["d"])
            for eid, f in entries
            if _id_tuple(eid) > _id_tuple(after_id)
        ][:limit]
        return records, False
    last_id = entries[-1][0]
    if _id_tuple(after_id) > _id_tuple(last_id):
        return [], False  # клиент впереди backlog'а — новых событий нет
    return [], True      # after_id вытеснен из ring → GAP


@dataclass
class EventRecord:
    """Одна запись backlog = одно SSE-событие."""

    id: str            # SSE event id / backlog entry id
    event_type: str
    data: str          # сериализованный payload (как в SSE data:)


@dataclass
class ReplayResult:
    records: list[EventRecord]
    gap: bool  # True → клиентский last-event-id вне backlog → нужен resync


def publish(
    kind: str,
    key: str,
    event_type: str,
    data: str,
    max_len: int = BACKLOG_MAXLEN,
) -> Optional[str]:
    """Записать событие в backlog; вернуть SSE id записи.

    Valkey предпочтителен (история переживает рестарт); при недоступности —
    in-memory ring (история процесса). Ошибка publish на valkey → None
    БЕЗ фолбэка в memory mid-stream: id-пространства режимов не смешиваются
    (инвариант SSE id == backlog id). Событие уходит без id; клиентский
    last-event-id остаётся предыдущим — resample не пропустит валидные
    записи, а на reconnect непрерывность не может быть подтверждена → gap
    → resync (честно, не тишина).
    """
    fields = {"t": event_type, "d": data}
    client = _get_valkey()
    if client is not None:
        stream = _stream_key(kind, key)
        try:
            event_id = client.xadd(stream, fields, maxlen=max_len, approximate=True)
            if isinstance(event_id, bytes):
                event_id = event_id.decode("utf-8")
            try:
                client.expire(stream, BACKLOG_TTL_S)  # sliding TTL
            except Exception:  # noqa: BLE001 — TTL best-effort
                pass
            return event_id
        except Exception:  # noqa: BLE001 — transient valkey failure
            logger.warning("[SSE:BACKLOG] valkey xadd failed — event recorded without id")
            return None
    # memory fallback (без valkey-клиента — по режиму, не по transient-сбою)
    return _ring_add(_stream_key(kind, key), fields)


def replay(
    kind: str,
    key: str,
    after_id: str,
    limit: int = 200,
) -> Optional[ReplayResult]:
    """Resample backlog после after_id.

    Возвращает None если хранилище недоступно/ошибка (caller → честная
    деградация: resync + флаг, не тишина). ReplayResult:
      * gap=False — события после after_id (возможно пусто: всё доставлено);
      * gap=True — непрерывность не подтверждена (TTL-вытеснение/триминг/
        рестарт в memory-режиме) → клиенту нужен resync-снапшот.
    """
    client = _get_valkey()
    if client is not None:
        try:
            return _replay_valkey(client, _stream_key(kind, key), after_id, limit)
        except Exception:  # noqa: BLE001 — valkey сбой → честная деградация
            logger.warning("[SSE:BACKLOG] valkey replay failed — caller must resync")
            return None
    with _ring_lock:
        records, gap = _ring_replay(_stream_key(kind, key), after_id, limit)
        return ReplayResult(records=records, gap=gap)


def _replay_valkey(client: Any, stream: str, after_id: str, limit: int) -> ReplayResult:
    entries = client.xrange(stream, min="-", max="+")
    norm: list[tuple[str, dict[str, str]]] = []
    for eid, fields in entries:
        eid_s = _dec(eid)
        norm.append((eid_s, {
            _dec(k): _dec(v) for k, v in fields.items()
        }))
    if not norm:
        # Пустой stream: история вытеснена TTL или ключа никогда не было —
        # если клиент называет last-event-id, непрерывность не подтвердить.
        return ReplayResult(records=[], gap=True)
    if any(eid == after_id for eid, _f in norm):
        records = [
            EventRecord(id=eid, event_type=f["t"], data=f["d"])
            for eid, f in norm
            if _id_tuple(eid) > _id_tuple(after_id)
        ][:limit]
        return ReplayResult(records=records, gap=False)
    last_id = norm[-1][0]
    if _id_tuple(after_id) > _id_tuple(last_id):
        return ReplayResult(records=[], gap=False)  # клиент впереди backlog'а
    return ReplayResult(records=[], gap=True)       # after_id вытеснен → GAP


def reset_backlog() -> None:
    """Сброс state (для тестов): клиенты и in-memory кольца."""
    global _valkey_client
    _valkey_client = None
    _rings.clear()
    _counters.clear()


def set_valkey_double(client: Any) -> None:
    """Подмена valkey-клиента тестовым double (COS-088 units)."""
    global _valkey_client
    _valkey_client = client
