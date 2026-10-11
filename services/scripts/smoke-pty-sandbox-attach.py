# -*- coding: utf-8 -*-
"""PTY-SANDBOX-1.1 live-smoke: attach-шов (HTTP-chunked) + доставка workspace.

Сценарий:
  1. build образов (сессия + сервис) → up pty-sandbox (профиль pty) → health;
     лимиты delivery сужены env-пробросом (2MB архив / 1MB распаковка) —
     негативы дешёвые и детерминированные;
  2. attach: сессия `cat` → GET /attach (фоновый читатель) + POST /stdin
     (chunked) → echo-поток идёт; resize (ок / кламп / 422); второй stdin → 409;
  3. exit-code: сессия `find` (сразу выходит) → status=exited/exit_code=0 →
     GET /attach → 409 + exit_code в деталях;
  4. delivery: tar → 201 → файлы видны и читаются процессом; read-only для
     процесса (touch → отказ; /tmp writable); идемпотентность (замена);
     негативы: oversize (declared CL) → 413, битый tar → 400, unsafe path →
     400, symlink → 400, чужой content-type → 415;
  5. изоляция не ослаблена: network none, ro-rootfs, нет docker.sock, нет сети;
  6. аудит: attach_*/delivery_* события в JSONL;
  7. cleanup: сессии удалены, сервис снят (стенд не затронут).

Self-skip (exit 0 + SKIP): docker недоступен.
Usage: python services/scripts/smoke-pty-sandbox-attach.py [--keep]
"""
from __future__ import annotations

import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSE = os.path.join(REPO_ROOT, "services", "docker-compose.yml")
IMAGE = "pty-sandbox-base:local"
API = "http://127.0.0.1:8190"
HOST, PORT = "127.0.0.1", 8190
KEEP = "--keep" in sys.argv

PASSED: list[str] = []
FAILED: list[str] = []
SIDS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run(cmd, timeout: int = 300, env=None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return 255, str(exc)


def api(method: str, path: str, body: dict | None = None, timeout: int = 30,
        raw: bytes | None = None, content_type: str | None = None):
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None)
    headers = {}
    if raw is not None:
        headers["Content-Type"] = content_type or "application/octet-stream"
    elif body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers=headers)
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
    except (urllib.error.URLError, http.client.HTTPException,
            ConnectionError, OSError) as exc:
        return 0, {"error": str(exc)}


def dk_exec(cid: str, argv: list[str], user: str | None = None) -> tuple[int, str]:
    cmd = ["docker", "exec"]
    if user:
        cmd += ["-u", user]
    cmd += [cid, *argv]
    return run(cmd, timeout=60)


def create_session(tool: str, ttl_s: int, run_id: str,
                   args: list[str] | None = None):
    return api("POST", "/sessions", {
        "run_id": run_id, "principal": "pty-smoke-11",
        "repo": "cosmo/pipeline-fixture",
        "commit_sha": "0f1e2d3c4b5a69788796a5b4c3d2e1f001234567",
        "tool": tool, "args": args or [], "ttl_s": ttl_s,
    })


def build_tar(entries) -> bytes:
    """entries: list[(name, bytes|None)] — None = DIRTYPE."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            if data is None:
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                tf.addfile(ti)
            else:
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def raw_oversize_probe(sid: str) -> str:
    """POST /workspace с гигантским declared Content-Length и без тела."""
    req = (f"POST /sessions/{sid}/workspace HTTP/1.1\r\n"
           f"Host: {HOST}:{PORT}\r\n"
           f"Content-Type: application/x-tar\r\n"
           f"Content-Length: 999999999\r\n"
           f"Connection: close\r\n\r\n").encode()
    try:
        with socket.create_connection((HOST, PORT), timeout=10) as s:
            s.sendall(req)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        return data.split(b"\r\n", 1)[0].decode("latin-1")
    except OSError as exc:
        return f"SOCKET-ERROR: {exc}"


def attach_reader(sid: str, sink: list, state: dict) -> None:
    """Фоновый читатель out-потока: read1 по чанкам.

    Без таймаутов: http.client читает через stdlib socket.SocketIO, у которого
    после таймаута «залипает» чтение ('cannot read from timed out object') и
    теряется буфер незавершённого чанка. read1 отдаёт по одному chunk'у.
    """
    conn = None
    try:
        conn = http.client.HTTPConnection(HOST, PORT, timeout=None)
        conn.request("GET", f"/sessions/{sid}/attach")
        resp = conn.getresponse()
        state["status"] = resp.status
        state["content_type"] = resp.getheader("Content-Type")
        while True:
            data = resp.read1(4096)
            if not data:
                state["ended"] = True
                break
            sink.append(data)
    except Exception as exc:  # noqa: BLE001
        state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def stdin_writer(sid: str, chunks: list[bytes], hold_s: float,
                 result: dict) -> None:
    """POST /stdin chunked: отправить чанки, подержать, завершить (EOF)."""
    conn = None
    try:
        conn = http.client.HTTPConnection(HOST, PORT, timeout=15)
        conn.putrequest("POST", f"/sessions/{sid}/stdin")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        for c in chunks:
            conn.send(b"%x\r\n" % len(c) + c + b"\r\n")
        time.sleep(hold_s)
        conn.send(b"0\r\n\r\n")
        resp = conn.getresponse()
        result["code"] = resp.status
        resp.read()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def kill_orphans() -> None:
    rc, out = run(["docker", "ps", "-aq",
                   "--filter", "label=managed-by=pty-sandbox"])
    ids = [i for i in out.split() if i]
    if ids:
        run(["docker", "rm", "-f", *ids], timeout=120)


def read_audit() -> list[dict]:
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
    return events


def main() -> int:
    print("=== PTY-SANDBOX-1.1 live-smoke (attach + delivery) ===")

    rc, out = run(["docker", "version", "--format", "{{.Server.Version}}"],
                  timeout=30)
    if rc != 0:
        print(f"[SKIP] docker недоступен: {out.strip()[:120]}")
        return 0
    if not os.path.exists(COMPOSE):
        print(f"[SKIP] compose не найден: {COMPOSE}")
        return 0

    env = dict(os.environ)
    env["PTY_SANDBOX_MAX_DELIVERY_MB"] = "2"      # негативы дешёвые
    env["PTY_SANDBOX_MAX_UNPACKED_MB"] = "1"

    try:
        # 1. образы + сервис
        rc, out = run(["docker", "build", "-t", IMAGE,
                       os.path.join(REPO_ROOT, "services", "pty-sandbox",
                                    "image")], timeout=600)
        check("sandbox-образ собран", rc == 0, f"rc={rc} {out.strip()[-120:]}")
        if rc != 0:
            return 1
        rc, out = run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                       "build", "pty-sandbox"], timeout=600)
        check("сервис-образ собран", rc == 0, f"rc={rc} {out.strip()[-120:]}")
        rc, out = run(["docker", "compose", "-f", COMPOSE, "--profile", "pty",
                       "up", "-d", "pty-sandbox"], timeout=900, env=env)
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
            rc, out = run(["docker", "logs", "pty-sandbox", "--tail", "40"],
                          timeout=60)
            print("  --- pty-sandbox logs ---")
            for line in out.splitlines()[-25:]:
                print("   |", line[:200])
            return 1

        code, hbody = api("GET", "/health")
        check("health: лимиты delivery из env (2MB/1MB)",
              hbody.get("max_delivery_mb") == 2 and hbody.get("max_unpacked_mb") == 1,
              str({k: hbody.get(k) for k in ("max_delivery_mb", "max_unpacked_mb")}))

        # аудит с чистого листа (volume живёт между прогонами)
        run(["docker", "exec", "pty-sandbox", "sh", "-c",
             ": > /var/log/pty-sandbox/audit.jsonl"], timeout=30)

        # ── 2. attach: cat + stdin + resize ─────────────────────────────
        code, body = create_session("cat", 180, "pty11-attach")
        check("attach: create 'cat' → 201", code == 201,
              f"HTTP {code} {str(body)[:120]}")
        if code != 201:
            return 1
        sid = body["session_id"]
        SIDS.append(sid)

        code, body = api("POST", f"/sessions/{sid}/resize",
                         {"rows": 40, "cols": 120})
        check("resize: 40x120 → 200", code == 200 and body.get("rows") == 40
              and body.get("cols") == 120, f"HTTP {code} {str(body)[:100]}")
        code, body = api("POST", f"/sessions/{sid}/resize",
                         {"rows": 99999, "cols": 1})
        check("resize: кламп (99999,1) → (500,1)",
              code == 200 and body.get("rows") == 500 and body.get("cols") == 1,
              f"HTTP {code} {str(body)[:100]}")
        code, _ = api("POST", f"/sessions/{sid}/resize", {"rows": 0, "cols": 10})
        check("resize: rows=0 → 422", code == 422, f"HTTP {code}")

        sink: list = []
        state: dict = {}
        reader = threading.Thread(target=attach_reader,
                                  args=(sid, sink, state), daemon=True)
        reader.start()
        time.sleep(0.8)
        check("attach: out-поток открыт (200, octet-stream)",
              state.get("status") == 200
              and "octet-stream" in str(state.get("content_type", "")),
              f"status={state.get('status')} ct={state.get('content_type')}")

        w1: dict = {}
        stdin_t = threading.Thread(target=stdin_writer,
                                   args=(sid, [b"hello-pty\n"], 1.2, w1),
                                   daemon=True)
        stdin_t.start()
        time.sleep(2.0)
        check("attach: stdin→stdout поток идёт (echo 'hello-pty')",
              b"hello-pty" in b"".join(sink), f"sink={b''.join(sink)[:80]!r}")
        check("attach: stdin-стрим завершился 204", w1.get("code") == 204,
              f"code={w1.get('code')} err={w1.get('error', '')}")

        # второй stdin при активном первом → 409
        w2: dict = {}
        busy_t = threading.Thread(target=stdin_writer,
                                  args=(sid, [b"x"], 2.5, w2), daemon=True)
        busy_t.start()
        time.sleep(0.8)
        code_b, body_b = api("POST", f"/sessions/{sid}/stdin", raw=b"")
        check("attach: второй stdin → 409 (single active)",
              code_b == 409, f"HTTP {code_b} {str(body_b)[:100]}")
        busy_t.join(timeout=8)
        check("attach: первый stdin освободил слот (204)", w2.get("code") == 204,
              f"code={w2.get('code')} err={w2.get('error', '')}")

        code, body = api("GET", f"/sessions/{sid}")
        check("attach: статус сессии с attach читается", code == 200,
              f"HTTP {code}")
        code, _ = api("DELETE", f"/sessions/{sid}")
        reader.join(timeout=8)
        check("attach: DELETE закрыл out-поток", state.get("ended") is True
              or state.get("error") is not None,
              f"ended={state.get('ended')} err={state.get('error')}")

        # ── 3. exit-code (find выходит сразу) ───────────────────────────
        code, body = create_session("find", 60, "pty11-exit",
                                    args=["/tmp", "-maxdepth", "0"])
        check("exit: create 'find' → 201", code == 201, f"HTTP {code}")
        sidD = body.get("session_id", "")
        if sidD:
            SIDS.append(sidD)
            status, ec = "", None
            deadline = time.time() + 25
            while time.time() < deadline:
                code, body = api("GET", f"/sessions/{sidD}")
                if code == 200:
                    status = str(body.get("status"))
                    ec = body.get("exit_code")
                    if status == "exited":
                        break
                time.sleep(1)
            check("exit: сессия завершилась (exited, code=0)",
                  status == "exited" and ec == 0, f"{status}/{ec}")
            code, body = api("GET", f"/sessions/{sidD}/attach")
            detail = body.get("detail") if isinstance(body, dict) else None
            check("exit: attach к exited → 409 + exit_code",
                  code == 409 and isinstance(detail, dict)
                  and detail.get("exit_code") == 0,
                  f"HTTP {code} {str(body)[:140]}")

        # ── 4. delivery ─────────────────────────────────────────────────
        code, body = create_session("cat", 240, "pty11-deliv")
        check("delivery: create 'cat' → 201", code == 201, f"HTTP {code}")
        if code != 201:
            return 1
        sidE = body["session_id"]
        cidE = body["container_id"]
        SIDS.append(sidE)

        tar_v1 = build_tar([
            ("README.md", b"delivered-v1\n"),
            ("src", None),
            ("src/main.py", b"print('v1')\n"),
        ])
        code, body = api("POST", f"/sessions/{sidE}/workspace", raw=tar_v1,
                         content_type="application/x-tar")
        check("delivery: tar → 201 (files=2, dirs=1)",
              code == 201 and body.get("files") == 2 and body.get("dirs") == 1,
              f"HTTP {code} {str(body)[:140]}")

        rc, out = dk_exec(cidE, ["cat", "/workspace/README.md"])
        check("delivery: файл виден и читается процессом", rc == 0
              and "delivered-v1" in out, f"rc={rc} out={out.strip()[:60]}")
        rc, out = dk_exec(cidE, ["ls", "/workspace"])
        check("delivery: дерево на месте (src/main.py)",
              rc == 0 and "src" in out, f"out={out.strip()[:80]}")

        rc, _ = dk_exec(cidE, ["sh", "-c", "touch /workspace/README.md"])
        check("delivery: файл read-only для процесса", rc != 0, f"rc={rc}")
        rc, _ = dk_exec(cidE, ["sh", "-c", "touch /workspace/newfile"])
        check("delivery: /workspace read-only для процесса", rc != 0, f"rc={rc}")
        rc, _ = dk_exec(cidE, ["sh", "-c", "touch /tmp/probe11"])
        check("delivery: /tmp (скретч) writable", rc == 0, f"rc={rc}")

        tar_v2 = build_tar([("second.md", b"second-only\n")])
        code, body = api("POST", f"/sessions/{sidE}/workspace", raw=tar_v2,
                         content_type="application/x-tar")
        check("delivery: повторная доставка заменяет (idempotent)",
              code == 201 and body.get("files") == 1, f"HTTP {code}")
        rc, out = dk_exec(cidE, ["cat", "/workspace/second.md"])
        rc2, _ = dk_exec(cidE, ["sh", "-c", "test ! -e /workspace/README.md"])
        check("delivery: старая версия убрана, новая на месте",
              rc == 0 and "second-only" in out and rc2 == 0,
              f"rc={rc} rc2={rc2}")

        status_line = raw_oversize_probe(sidE)
        check("delivery negative: oversize (declared CL) → 413",
              "413" in status_line, status_line[:80])
        code, body = api("POST", f"/sessions/{sidE}/workspace", raw=b"not a tar",
                         content_type="application/x-tar")
        check("delivery negative: битый tar → 400 (bad_archive)",
              code == 400 and "bad_archive" in str(body), f"HTTP {code}")
        code, body = api("POST", f"/sessions/{sidE}/workspace",
                         raw=build_tar([("../evil.txt", b"x")]),
                         content_type="application/x-tar")
        check("delivery negative: traversal → 400 (unsafe_path)",
              code == 400 and "unsafe_path" in str(body), f"HTTP {code}")
        link_buf = io.BytesIO()
        with tarfile.open(fileobj=link_buf, mode="w:") as tf:
            ti = tarfile.TarInfo("link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
        code, body = api("POST", f"/sessions/{sidE}/workspace",
                         raw=link_buf.getvalue(),
                         content_type="application/x-tar")
        check("delivery negative: symlink → 400 (unsupported_entry)",
              code == 400 and "unsupported_entry" in str(body), f"HTTP {code}")
        code, _ = api("POST", f"/sessions/{sidE}/workspace", raw=b"x",
                      content_type="text/plain")
        check("delivery negative: чужой content-type → 415", code == 415,
              f"HTTP {code}")

        # ── 5. изоляция не ослаблена ────────────────────────────────────
        rc, out = run(["docker", "inspect", cidE], timeout=60)
        insp = json.loads(out)[0] if rc == 0 else {}
        hc = insp.get("HostConfig", {})
        check("изоляция: network none", hc.get("NetworkMode") == "none",
              str(hc.get("NetworkMode")))
        check("изоляция: read-only rootfs", hc.get("ReadonlyRootfs") is True)
        rc, _ = dk_exec(cidE, ["sh", "-c", "test ! -e /var/run/docker.sock"])
        check("изоляция: нет /var/run/docker.sock", rc == 0)
        rc, out = dk_exec(cidE, ["sh", "-c",
                                 "wget -T 2 -q -O- http://cosmo-api:8100/live"])
        check("изоляция: нет сети (egress fail)", rc != 0, f"rc={rc}")
        rc, out = dk_exec(cidE, ["sh", "-c", "stat -c %a /workspace"])
        check("изоляция: /workspace mode 755 (RO для процесса)",
              rc == 0 and out.strip() == "755", f"out={out.strip()[:20]}")

        # ── 6. аудит ────────────────────────────────────────────────────
        events = read_audit()
        names = [e.get("event") for e in events]
        check("аудит: attach_open/attach_close", "attach_open" in names
              and "attach_close" in names, str(names[:10])[:140])
        check("аудит: attach_stdin_open/close", "attach_stdin_open" in names
              and "attach_stdin_close" in names)
        check("аудит: attach_denied (stdin_busy)",
              any(e.get("event") == "attach_denied"
                  and e.get("reason") == "stdin_busy" for e in events))
        check("аудит: attach_denied (not_running)",
              any(e.get("event") == "attach_denied"
                  and e.get("reason") == "not_running" for e in events))
        check("аудит: delivery_ok ≥2",
              names.count("delivery_ok") >= 2, str(names.count("delivery_ok")))
        denied = [e.get("reason") for e in events
                  if e.get("event") == "delivery_denied"]
        check("аудит: delivery_denied (oversize/bad/unsafe/unsupported)",
              all(r in denied for r in ("oversize", "bad_archive", "unsafe_path",
                                        "unsupported_entry")),
              str(denied))

    finally:
        for sid in SIDS:
            try:
                api("DELETE", f"/sessions/{sid}", timeout=10)
            except Exception:  # noqa: BLE001
                pass
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
    print("=== PTY-SANDBOX-1.1 smoke: PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
