# -*- coding: utf-8 -*-
"""PTY-SANDBOX-1 live-smoke: sandbox-сервис, изоляция §5, TTL, аудит, default-off.

Сценарий:
  1. default-off: без профиля "pty" сервис отсутствует в конфиге стенда
     (с `--profile pty` — присутствует);
  2. build sandbox-образа → up pty-sandbox (профиль pty) → health;
  3. deny: tool вне allowlist → 403 + аудит-запись;
  4. create: изолированная сессия (tool=cat) → профиль §5 по docker inspect
     (network none, ro-rootfs, cap-drop ALL, no-new-privileges, non-root, лимиты);
  5. негативы изнутри: non-root; нет docker.sock; нет сети; ro-rootfs;
     tmpfs writable; второй рубеж allowlist (sandbox-run sh → deny);
  6. TTL: сессия убивается reaper'ом (hard_ttl);
  7. stop: DELETE → status=stopped, reason=requested;
  8. аудит: JSONL содержит create/deny/kill-события;
  9. cleanup: сессии удалены; сервис снят (стенд не затронут).

Self-skip (exit 0 + SKIP): docker/compose недоступны.
Usage: python services/scripts/smoke-pty-sandbox.py [--keep]
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSE = os.path.join(REPO_ROOT, "services", "docker-compose.yml")
IMAGE = "pty-sandbox-base:local"
API = "http://127.0.0.1:8190"
KEEP = "--keep" in sys.argv

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return 255, str(exc)


def api(method: str, path: str, body: dict | None = None,
        timeout: int = 30) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, (json.loads(payload) if payload else {})
        except ValueError:
            return exc.code, {"raw": payload[:200]}
    except (urllib.error.URLError, http.client.HTTPException, ConnectionError, OSError) as exc:
        # Старт сервиса: docker-proxy принимает TCP раньше uvicorn —
        # RemoteDisconnected/ConnectionError штатны, caller ретраит.
        return 0, {"error": str(exc)}


def dk_exec(cid: str, argv: list[str]) -> tuple[int, str]:
    return run(["docker", "exec", cid, *argv], timeout=60)


def session_body(tool: str, ttl_s: int, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "principal": "pty-smoke",
        "repo": "cosmo/pipeline-fixture",
        "commit_sha": "0f1e2d3c4b5a69788796a5b4c3d2e1f001234567",
        "tool": tool,
        "args": [],
        "ttl_s": ttl_s,
    }


def kill_orphans() -> None:
    rc, out = run(["docker", "ps", "-aq",
                   "--filter", "label=managed-by=pty-sandbox"])
    ids = [i for i in out.split() if i]
    if ids:
        run(["docker", "rm", "-f", *ids], timeout=120)


def main() -> int:
    print("=== PTY-SANDBOX-1 live-smoke ===")

    rc, out = run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=30)
    if rc != 0:
        print(f"[SKIP] docker недоступен: {out.strip()[:120]}")
        return 0
    if not os.path.exists(COMPOSE):
        print(f"[SKIP] compose не найден: {COMPOSE}")
        return 0

    # 1. default-off (до любых поднятий)
    rc, out = run(["docker", "compose", "-f", COMPOSE, "config", "--services"],
                  timeout=120)
    base_services = out.split() if rc == 0 else []
    check("default-off: без профиля pty-sandbox отсутствует",
          rc == 0 and "pty-sandbox" not in base_services,
          f"rc={rc}")
    rc, out = run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                   "config", "--services"], timeout=120)
    prof_services = out.split() if rc == 0 else []
    check("профиль pty: pty-sandbox присутствует",
          rc == 0 and "pty-sandbox" in prof_services, f"rc={rc}")

    try:
        # 2. sandbox-образ + сервис
        rc, out = run(["docker", "build", "-t", IMAGE,
                       os.path.join(REPO_ROOT, "services", "pty-sandbox", "image")],
                      timeout=600)
        check("sandbox-образ собран", rc == 0, f"rc={rc} {out.strip()[-120:]}")
        if rc != 0:
            return 1

        rc, out = run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                       "build", "pty-sandbox"], timeout=600)
        check("сервис-образ собран (1.1)", rc == 0, f"rc={rc} {out.strip()[-120:]}")

        rc, out = run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                       "up", "-d", "pty-sandbox"], timeout=900)
        check("pty-sandbox поднят (профиль pty)", rc == 0,
              f"rc={rc} {out.strip()[-160:]}")

        healthy = False
        deadline = time.time() + 120
        while time.time() < deadline:
            code, _ = api("GET", "/health", timeout=5)
            if code == 200:
                healthy = True
                break
            time.sleep(3)
        check("health :8190/health = 200", healthy)
        if not healthy:
            rc, out = run(["docker", "logs", "pty-sandbox", "--tail", "40"], timeout=60)
            print("  --- pty-sandbox logs ---")
            for line in out.splitlines()[-25:]:
                print("   |", line[:200])
            return 1

        # 3. deny вне allowlist
        code, body = api("POST", "/sessions", session_body("sh", 60, "pty-smoke-deny"))
        check("deny: tool 'sh' → 403", code == 403, f"HTTP {code}")

        # 4. create сессии + профиль изоляции
        code, body = api("POST", "/sessions", session_body("cat", 8, "pty-smoke-ttl"))
        check("create: tool 'cat' → 201", code == 201, f"HTTP {code} {str(body)[:120]}")
        if code != 201:
            return 1
        sid = body["session_id"]
        cid = body["container_id"]

        rc, out = run(["docker", "inspect", cid], timeout=60)
        insp = json.loads(out)[0] if rc == 0 else {}
        hc = insp.get("HostConfig", {})
        mounts = insp.get("Mounts", []) or []
        tmpfs_cfg = hc.get("Tmpfs") or {}
        mount_dests = sorted({m.get("Destination") for m in mounts})

        check("изоляция: network none", hc.get("NetworkMode") == "none",
              str(hc.get("NetworkMode")))
        check("изоляция: read-only rootfs", hc.get("ReadonlyRootfs") is True)
        check("изоляция: cap-drop ALL", hc.get("CapDrop") == ["ALL"],
              str(hc.get("CapDrop")))
        check("изоляция: no-new-privileges",
              any("no-new-privileges" in s for s in (hc.get("SecurityOpt") or [])))
        check("изоляция: non-root user", insp.get("Config", {}).get("User") == "sandbox")
        check("изоляция: mem limit 256m", hc.get("Memory") == 256 * 1024 * 1024,
              str(hc.get("Memory")))
        check("изоляция: pids limit 128", hc.get("PidsLimit") == 128,
              str(hc.get("PidsLimit")))
        check("изоляция: только tmpfs-маунты (/workspace, /tmp), нет host-mounts",
              sorted(tmpfs_cfg.keys()) == ["/tmp", "/workspace"] and not mounts,
              f"tmpfs={sorted(tmpfs_cfg.keys())} mounts={mount_dests}")

        # 5. негативы изнутри
        rc, out = dk_exec(cid, ["id", "-u"])
        check("внутри: uid=1000 (non-root)", rc == 0 and out.strip() == "1000",
              out.strip())
        rc, _ = dk_exec(cid, ["sh", "-c", "test ! -e /var/run/docker.sock"])
        check("внутри: нет /var/run/docker.sock", rc == 0)
        rc, _ = dk_exec(cid, ["sh", "-c", "test ! -e /host"])
        check("внутри: нет host-путей", rc == 0)
        rc, out = dk_exec(cid, ["sh", "-c",
                                "wget -T 2 -q -O- http://cosmo-api:8100/live"])
        check("внутри: нет сети (egress fail)", rc != 0, f"rc={rc}")
        rc, _ = dk_exec(cid, ["sh", "-c", "touch /probe-root"])
        check("внутри: rootfs read-only", rc != 0)
        rc, _ = dk_exec(cid, ["sh", "-c", "touch /tmp/probe"])
        check("внутри: tmpfs /tmp writable", rc == 0)
        rc, _ = dk_exec(cid, ["sh", "-c", "touch /workspace/probe"])
        check("внутри: /workspace read-only для процесса (1.1)", rc != 0)
        rc, _ = dk_exec(cid, ["/usr/local/bin/sandbox-run", "sh", "-c", "id"])
        check("второй рубеж: sandbox-run 'sh' → deny (77)", rc == 77, f"rc={rc}")

        # 6. TTL hard_ttl (ttl_s=8)
        status, reason = "", ""
        deadline = time.time() + 45
        while time.time() < deadline:
            code, body = api("GET", f"/sessions/{sid}", timeout=10)
            if code == 200 and isinstance(body, dict):
                status = str(body.get("status"))
                reason = str(body.get("kill_reason"))
                if status in ("killed", "stopped", "exited"):
                    break
            time.sleep(2)
        check("TTL: сессия убита по hard_ttl", status == "killed" and reason == "hard_ttl",
              f"status={status} reason={reason}")

        # 7. stop по запросу
        code, body = api("POST", "/sessions", session_body("cat", 120, "pty-smoke-stop"))
        sid2 = body.get("session_id") if code == 201 else ""
        check("create: вторая сессия → 201", code == 201, f"HTTP {code}")
        if sid2:
            code, body = api("DELETE", f"/sessions/{sid2}", timeout=30)
            check("stop: DELETE → stopped/requested",
                  code == 200 and body.get("status") == "stopped"
                  and body.get("kill_reason") == "requested",
                  f"HTTP {code} {str(body)[:100]}")

        # 8. аудит
        rc, out = run(["docker", "exec", "pty-sandbox", "cat",
                       "/var/log/pty-sandbox/audit.jsonl"], timeout=60)
        events = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
        names = [e.get("event") for e in events]
        check("аудит: session_denied записан", "session_denied" in names)
        check("аудит: session_create записан", names.count("session_create") >= 2,
              str(names[:8]))
        check("аудит: session_kill (hard_ttl) записан",
              any(e.get("event") == "session_kill" and e.get("reason") == "hard_ttl"
                  for e in events))
        check("аудит: session_kill (requested/stopped) записан",
              any(e.get("event") == "session_kill" and e.get("final_status") == "stopped"
                  for e in events))

    finally:
        kill_orphans()
        if not KEEP:
            run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                 "rm", "-sf", "pty-sandbox"], timeout=300)

    print("---")
    print(f"passed={len(PASSED)} failed={len(FAILED)}")
    if FAILED:
        for f in FAILED:
            print(f"  FAILED: {f}")
        return 1
    print("=== PTY-SANDBOX-1 smoke: PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
