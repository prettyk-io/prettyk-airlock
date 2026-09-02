#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""COS-089: Scratch janitor CLI — listing/drop orphan test-scratch databases.

Targets the ISOLATED test PG instance (default 127.0.0.1:5433) and cleans:

- ``cosmo_test_s*``  — per-session test DBs (COS-076, _testpg session mode);
  a live worker's session DB holds connections — skipped, not dropped;
  leftovers without connections (SIGKILL'd session, atexit miss) — orphans.
- ``cosmo_scratch_*`` — migration scratch DBs (COS-078 scratch_name /
  COS-089 verification): dropped normally by tests; leftovers are orphans.

Safety contract:
- DRY-RUN by default (plan only); ``--apply`` performs the drop explicitly.
- Drops ONLY databases matching the two prefixes AND having zero active
  connections. Anything else (live session DB, non-scratch name) is reported
  and skipped.
- Protected names are never candidates: postgres, template0/1, cosmo (dev),
  cosmo_test (shared main test DB).
- Refuses to run against the dev stand (host port 5432) — hard fail.
- Not a daemon: one-shot, exits after the report.

Exit codes: 0 = ok (plan/drop completed); 2 = target unreachable / guard trip.
"""
from __future__ import annotations

import argparse
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5433  # test PG; 5432 is the dev stand — forbidden
DEFAULT_USER = "cosmo"
DEFAULT_PASSWORD = "cosmo"

PROTECTED = {"postgres", "template0", "template1", "cosmo", "cosmo_test"}
PREFIXES = ("cosmo_test_s", "cosmo_scratch_")

DEV_STAND_PORT = 5432


def _connect_admin(args):
    import psycopg2

    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname="postgres",
        user=args.user,
        password=args.password,
        connect_timeout=5,
    )


def _candidates(cur) -> list[dict]:
    """Scratch-prefixed DBs с числом активных соединений и размером."""
    cur.execute(
        """
        SELECT d.datname,
               (SELECT count(*) FROM pg_stat_activity a
                 WHERE a.datname = d.datname) AS conns,
               pg_size_pretty(pg_database_size(d.datname)) AS size
        FROM pg_database d
        WHERE d.datallowconn
        ORDER BY d.datname
        """
    )
    out = []
    for name, conns, size in cur.fetchall():
        lower = name.lower()
        if lower in PROTECTED:
            continue
        if not lower.startswith(PREFIXES):
            continue
        out.append({"name": name, "conns": int(conns), "size": size})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="COS-089 scratch janitor: dry-run plan / --apply drop of "
        "orphan cosmo_test_s* / cosmo_scratch_* databases on the test PG."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the drop (default: dry-run plan only)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable plan/report on stdout",
    )
    args = parser.parse_args()

    if args.port == DEV_STAND_PORT:
        print(
            f"[GUARD] refusing to run against host port {DEV_STAND_PORT} "
            "(dev stand). Test PG lives on 5433.",
            file=sys.stderr,
        )
        return 2

    try:
        conn = _connect_admin(args)
        # COS-089: DROP DATABASE запрещён внутри транзакционного блока —
        # вся работа джанитора идёт в autocommit.
        conn.autocommit = True
    except Exception as exc:
        print(f"[FAIL] test PG unreachable on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2

    try:
        cur = conn.cursor()
        candidates = _candidates(cur)
        orphans = [c for c in candidates if c["conns"] == 0]
        active = [c for c in candidates if c["conns"] > 0]

        if args.json:
            import json

            print(json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "orphans": orphans,
                    "active_skipped": active,
                    "dropped": [c["name"] for c in orphans] if args.apply else [],
                },
                indent=2,
            ))
        else:
            mode = "APPLY" if args.apply else "DRY-RUN (--apply to execute)"
            print(f"SCRATCH JANITOR [{mode}] on {args.host}:{args.port}")
            if not candidates:
                print("  no scratch-prefixed databases — nothing to do")
            for c in orphans:
                action = "DROP" if args.apply else "would drop"
                print(f"  [{action}] {c['name']}  (conns=0, size={c['size']})")
            for c in active:
                print(f"  [skip]    {c['name']}  (conns={c['conns']} — live session)")

        if args.apply:
            for c in orphans:
                if args.json:
                    print(f"[drop] {c['name']}")
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (c["name"],),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{c["name"]}"')
                if not args.json:
                    print(f"  dropped: {c['name']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
