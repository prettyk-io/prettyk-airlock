# -*- coding: utf-8 -*-
"""COS-064: e2e helper — publish/clean/count notifications.

Использует PRODUCTION код-путь: NotificationManager.record_event (transactional
outbox) через тот же async session, что и backend. Обработка — через живой
backend API (POST /api/v1/notifications/process), как в бою.

Команды:
  publish --type run_failed --aggregate run/run-e2e-1 --title "T" --message "M" [--event-id X] [--severity high]
  clean                        — очистить notification_events + notification_inbox
  unread --recipient operator  — количество непрочитанных (прямой SQL)
  dlq-fixture [--title "T"]    — вставить failed email-строку в DLQ (прямой SQL;
                                 provider стенда всегда accept, поэтому DLQ через
                                 продакшн-путь на стенде недостижима)

Recipient V1: 'operator' — fixed contract (AlertHUD + SSE stream).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

# Repo root = frontend/e2e/helpers/<this>.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.cosmo.db.session import get_sessionmaker, get_sync_url  # noqa: E402
from orchestrator.cosmo.notifications.manager import NotificationManager  # noqa: E402


def _mint_jwt(sub: str, roles: list[str], is_admin: bool = False) -> str:
    """COS-092: COS-085 закрыл opaque-bearer — только JWT (`ey...payload...`).
    Подпись на deps-слое не проверяется (COS-031), поэтому e2e минтит
    локальный unsigned JWT — честный credential для стенда."""
    import base64

    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    claims: dict = {"sub": sub, "roles": roles}
    if is_admin:
        claims["is_admin"] = True
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}.e2e"


async def _publish(args: argparse.Namespace) -> None:
    event_type = args.type
    aggregate_type, _, aggregate_id = args.aggregate.partition("/")
    mgr = NotificationManager()
    async with get_sessionmaker()() as session:
        row, created = await mgr.record_event(
            session,
            event_type=event_type,
            aggregate_type=aggregate_type or "run",
            aggregate_id=aggregate_id or args.aggregate,
            event_id=args.event_id,
            title=args.title,
            message=args.message,
            severity=args.severity,
            explicit_recipients=["operator"],
        )
        await session.commit()
    if not created:
        print(json.dumps({"ok": True, "event_id": row.event_id, "dedup": True}))
        return
    # Process через живой backend — production путь fanout.
    # POST /process идемпотентен (UNIQUE(event_id, recipient, channel)),
    # поэтому retry безопасен: SSE-коннекты могут конкурировать за uvicorn.
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                "http://localhost:8100/api/v1/notifications/process", method="POST"
            )
            req.add_header(
                "Authorization",
                "Bearer " + _mint_jwt("e2e-ops", ["admin_sec"], is_admin=True),
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            _wait_inbox_row(row.event_id)
            print(json.dumps({"ok": True, "event_id": row.event_id, "process": body}))
            return
        except Exception as exc:  # noqa: BLE001 — retry any transport error
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"process endpoint failed after retries: {last_err}")


def _wait_inbox_row(event_id: str, timeout_s: float = 15.0) -> None:
    """Ждать появления inbox-строки события (fanout завершён).

    Race: worker (10s тик) и POST /process конкурируют за SKIP LOCKED —
    POST мог вернуть 0 processed, а worker ещё коммитит. Fixture обязана
    быть детерминированной: ждём фактический fanout в notification_inbox.
    """
    import psycopg2

    url = _sync_url().replace("postgresql+psycopg2://", "postgresql://")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with psycopg2.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM notification_inbox WHERE event_id = %s",
                        (event_id,),
                    )
                    n = cur.fetchone()[0]
            if n >= 1:
                return
        except psycopg2.OperationalError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"inbox row for {event_id} did not appear within {timeout_s}s")


def _sync_url() -> str:
    return get_sync_url()


def _sql_exec(sql: str) -> None:
    import psycopg2

    url = _sync_url().replace("postgresql+psycopg2://", "postgresql://")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with psycopg2.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            return
        except psycopg2.OperationalError as exc:
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"SQL failed after retries: {last_err}")


def _dlq_fixture(args: argparse.Namespace) -> None:
    """COS-079: seeded terminal-failed email row (state='failed' → DLQ).

    Прямая вставка: LoggingEmailProvider стенда всегда accepted=True,
    терминальный fail через продакшн-путь недостижим. Replay на стенде
    уйдёт в 'sent' — это и есть честное поведение провайдера стенда.
    """
    import psycopg2
    import uuid

    event_id = f"evt-dlq-{uuid.uuid4().hex[:12]}"
    row_id = f"dlq-{uuid.uuid4().hex[:12]}"
    title = args.title or "E2E DLQ item"
    url = _sync_url().replace("postgresql+psycopg2://", "postgresql://")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with psycopg2.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO notification_events "
                        "(event_id, event_type, aggregate_type, aggregate_id, "
                        " occurred_at, payload, recipient_count, processed, created_at) "
                        "VALUES (%s, 'run_failed', 'run', 'r-e2e-dlq', NOW(), '{}', 1, true, NOW()) "
                        "ON CONFLICT (event_id) DO NOTHING",
                        (event_id,),
                    )
                    cur.execute(
                        "INSERT INTO notification_inbox "
                        "(id, event_id, recipient_id, channel, notification_type, "
                        " severity, title, message, state, attempts, max_attempts, "
                        " last_error, created_at, updated_at) "
                        "VALUES (%s, %s, 'ops@company.io', 'email', 'run_failed', "
                        " 'high', %s, 'dlq fixture row', 'failed', 5, 5, "
                        " 'smtp down', NOW(), NOW())",
                        (row_id, event_id, title),
                    )
                conn.commit()
            print(json.dumps({"ok": True, "id": row_id, "event_id": event_id}))
            return
        except psycopg2.OperationalError as exc:
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"dlq-fixture failed after retries: {last_err}")


def _clean() -> None:
    _sql_exec("DELETE FROM notification_inbox")
    _sql_exec("DELETE FROM notification_events")
    print(json.dumps({"ok": True, "cleaned": True}))


def _unread(args: argparse.Namespace) -> None:
    import psycopg2

    url = _sync_url().replace("postgresql+psycopg2://", "postgresql://")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with psycopg2.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM notification_inbox "
                        "WHERE recipient_id = %s AND channel = 'in_app' AND read_at IS NULL",
                        (args.recipient,),
                    )
                    n = cur.fetchone()[0]
            print(json.dumps({"unread": n}))
            return
        except psycopg2.OperationalError as exc:
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"unread query failed after retries: {last_err}")


def _run_publish(args: argparse.Namespace) -> str:
    return asyncio.run(_publish(args))


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("publish")
    pp.add_argument("--type", required=True)
    pp.add_argument("--aggregate", required=True)
    pp.add_argument("--title", default="")
    pp.add_argument("--message", default="")
    pp.add_argument("--event-id", default=None)
    pp.add_argument("--severity", default=None)
    pp.set_defaults(func=_run_publish)

    sub.add_parser("clean").set_defaults(func=lambda _a: _clean())

    pd = sub.add_parser("dlq-fixture")
    pd.add_argument("--title", default="E2E DLQ item")
    pd.set_defaults(func=_dlq_fixture)

    pu = sub.add_parser("unread")
    pu.add_argument("--recipient", default="operator")
    pu.set_defaults(func=_unread)

    args = p.parse_args()
    result = args.func(args)
    if isinstance(result, str):
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
