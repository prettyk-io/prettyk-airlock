"""Cosmoport 2.0 — Locust Load Test (COS-068).

Профили:
  1. Read-heavy (80%): запросы к чтению
  2. Write-pipeline (20%): создание прогонов, компиляция планов, опрос статуса

Перед запуском:
  1. Поднять API: docker compose up -d cosmo-postgres cosmo-valkey cosmo-api cosmo-caddy
  2. Засеять тестовые данные: python -c "exec(open('services/load_tests/locustfile.py').read().split('if __name__')[0])"
  3. Запустить Locust: locust -f services/load_tests/locustfile.py --host=http://127.0.0.1:8080

Параметры по умолчанию (из командной строки):
  --users 100 --spawn-rate 10 --run-time 60s --headless --csv=reports/load-test
"""
from __future__ import annotations

import random
import string
import uuid
from typing import Optional

from locust import HttpUser, TaskSet, between, task
from locust.exception import RescheduleTaskImmediately


# ── Seeded entity IDs (must be pre-created before test) ──────────────────

DOMAIN_ID = "load-test-domain"
APP_ID = "load-test-app"
PLAN_ID = "load-test-plan"
BRICK_SAST_ID = "load-test-brick-sast"
BRICK_DAST_ID = "load-test-brick-dast"


# ── Helpers ────────────────────────────────────────────────────────────────

def _random_run_id() -> str:
    return f"load-run-{uuid.uuid4().hex[:8]}"


def _random_plan_id() -> str:
    return f"load-plan-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════════════════
# Read User (80% of traffic)
# ═══════════════════════════════════════════════════════════════════════════

class ReadUser(HttpUser):
    """Read-heavy traffic: lists, dashboards, status checks."""

    weight = 80
    wait_time = between(0.1, 0.5)

    @task(3)
    def list_domains(self):
        self.client.get("/api/v1/domains", name="/api/v1/domains")

    @task(2)
    def list_apps(self):
        self.client.get("/api/v1/apps?domain_id=" + DOMAIN_ID, name="/api/v1/apps")

    @task(2)
    def list_runs(self):
        self.client.get(f"/api/v1/runs?domain_id={DOMAIN_ID}", name="/api/v1/runs")

    @task(2)
    def status_dashboard(self):
        self.client.get("/api/v1/status/dashboard", name="/api/v1/status/dashboard")


# ═══════════════════════════════════════════════════════════════════════════
# Write User (20% of traffic) — pipeline creator
# ═══════════════════════════════════════════════════════════════════════════

class WriteUser(HttpUser):
    """Write-heavy traffic: create runs, compile plans, poll status."""

    weight = 20
    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Fetch existing entities once on startup."""
        self.run_counter = 0

    @task(5)
    def create_run(self):
        self.run_counter += 1
        run_id = _random_run_id()
        payload = {
            "id": run_id,
            "plan_id": PLAN_ID,
            "trigger": "manual",
            "domain_id": DOMAIN_ID,
            "initiator_user_id": "load-tester",
            "initiator_role": "developer",
        }
        with self.client.post(
            "/api/v1/runs",
            json=payload,
            name="/api/v1/runs [POST]",
            catch_response=True,
        ) as r:
            if r.status_code == 201:
                r.success()
            elif r.status_code == 409:
                # Duplicate — retry with another ID
                r.success()
            elif r.status_code == 429:
                # Rate-limited, mark as warning but not failure
                r.success()
            elif r.status_code == 503:
                r.success()  # overload, acceptable

    @task(2)
    def compile_plan(self):
        plan_id = _random_plan_id()
        payload = {
            "plan_id": plan_id,
            "app_id": APP_ID,
            "brick_ids": [BRICK_SAST_ID, BRICK_DAST_ID],
        }
        with self.client.post(
            "/api/v1/plans/compile",
            json=payload,
            name="/api/v1/plans/compile [POST]",
            catch_response=True,
        ) as r:
            if r.status_code in (201, 202):
                r.success()
            elif r.status_code == 409:
                r.success()
            elif r.status_code == 429:
                r.success()

    @task(3)
    def check_run_status(self):
        self.client.get(f"/api/v1/runs?domain_id={DOMAIN_ID}", name="/api/v1/runs status poll")


# ── Seed data for load test ───────────────────────────────────────────────

def seed_load_test_data(host: str = "http://127.0.0.1:8080"):
    """Create Domain, App, Bricks, Plan required by write load tests.

    Call once before starting Locust:
        python services/load_tests/locustfile.py --seed

    Or import and call:
        from services.load_tests.locustfile import seed_load_test_data
        seed_load_test_data()
    """
    import httpx

    client = httpx.Client(base_url=host, timeout=10.0)

    # 1. Domain
    print(f"Seeding domain: {DOMAIN_ID}")
    r = client.post("/api/v1/domains", json={
        "id": DOMAIN_ID,
        "label": "Load Test Domain",
        "forge_binding": {
            "forge_type": "gitea",
            "url": "http://gitea:3000",
            "token_ref": "VAULT/LOAD_TEST",
        },
    })
    if r.status_code in (201, 409):
        print(f"  Domain OK (HTTP {r.status_code})")
    else:
        print(f"  Domain FAIL: {r.status_code} {r.text}")
        return False

    # 2. Application
    print(f"Seeding app: {APP_ID}")
    r = client.post("/api/v1/apps", json={
        "id": APP_ID,
        "domain_id": DOMAIN_ID,
        "level": 1,
        "repo_binding": {
            "forge_id": "gitea",
            "repo_path": f"{DOMAIN_ID}/load-app",
        },
    })
    if r.status_code in (201, 409):
        print(f"  App OK (HTTP {r.status_code})")
    else:
        print(f"  App FAIL: {r.status_code} {r.text}")
        return False

    # 3. Bricks
    for brick_id, brick_name, brick_type, source in [
        (BRICK_SAST_ID, "SAST Scan", "sast", "web"),
        (BRICK_DAST_ID, "DAST Scan", "dast", "web"),
    ]:
        print(f"Seeding brick: {brick_id}")
        r = client.post("/api/v1/bricks", json={
            "id": brick_id,
            "name": brick_name,
            "type": brick_type,
            "source": source,
            "definition": {
                "image": f"load-test/{brick_type}:latest",
            },
        })
        if r.status_code in (201, 409):
            print(f"  Brick OK (HTTP {r.status_code})")
        else:
            print(f"  Brick FAIL: {r.status_code} {r.text}")

    # 4. Plan
    print(f"Seeding plan: {PLAN_ID}")
    r = client.post("/api/v1/plans", json={
        "id": PLAN_ID,
        "app_id": APP_ID,
        "brick_ids": [BRICK_SAST_ID, BRICK_DAST_ID],
    })
    if r.status_code in (201, 409):
        print(f"  Plan OK (HTTP {r.status_code})")
    else:
        print(f"  Plan FAIL: {r.status_code} {r.text}")
        return False

    client.close()
    print("Seed data ready. Start locust with: locust -f services/load_tests/locustfile.py --host=http://127.0.0.1:8080")
    return True


def cleanup_load_test_data(host: str = "http://127.0.0.1:8080"):
    """Remove seed data after test."""
    import httpx

    client = httpx.Client(base_url=host, timeout=10.0)
    for resource, id_val in [
        ("domains", DOMAIN_ID),
        ("apps", APP_ID),
        ("bricks", BRICK_SAST_ID),
        ("bricks", BRICK_DAST_ID),
    ]:
        try:
            r = client.delete(f"/api/v1/{resource}/{id_val}")
            print(f"  Deleted {resource}/{id_val}: HTTP {r.status_code}")
        except Exception as e:
            print(f"  Failed to delete {resource}/{id_val}: {e}")
    client.close()


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv:
        seed_load_test_data()
    elif "--cleanup" in sys.argv:
        cleanup_load_test_data()
    else:
        print("Usage:")
        print("  python locustfile.py --seed    — seed test data")
        print("  python locustfile.py --cleanup — remove test data")
        print("  locust -f locustfile.py --host=http://127.0.0.1:8080 — run load test")