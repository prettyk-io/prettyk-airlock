# -*- coding: utf-8 -*-
"""COS-094: prod edge — nginx same-origin API proxy + airgap profile.

Статические контракты edge-конфигов (без docker — файлы репозитория):

1. frontend/nginx.conf: /api проксируется на cosmo-api (не съедается
   SPA-fallback → SPA-HTML/405), SSE-ручки без буферизации с long timeout,
   health-ручки passthrough честного /ready (COS-090), DNS только через
   Docker embedded resolver (airgap-безопасно).
2. services/Caddyfile: SSE flush_interval -1, rate limit /api* —
   канонический внешний edge не противоречит same-origin nginx.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        pytest.skip(f"{rel} not found")
    return p.read_text(encoding="utf-8")


class TestNginxSameOriginEdge:
    """nginx 5174: SPA + same-origin /api (COS-094)."""

    @pytest.fixture(scope="class")
    def conf(self) -> str:
        return _read("frontend/nginx.conf")

    def test_api_proxied_to_cosmo_api(self, conf):
        """/api/ → cosmo-api:8100; SPA-fallback не съедает API-запросы."""
        assert "proxy_pass http://$api_upstream" in conf
        assert "set $api_upstream cosmo-api:8100" in conf
        # SPA-fallback идёт последним и не матчит /api
        assert conf.index("location /api/") < conf.index("location / {")

    def test_sse_locations_unbuffered_with_long_timeout(self, conf):
        """SSE: buffering off, long read timeout (поток живой, чанки сразу)."""
        sse_idx = conf.find("^/api/v1/(runs/[^/]+/stream|domains/[^/]+/events/stream|notifications/stream)$")
        assert sse_idx != -1, "combined SSE location missing"
        sse_block = conf[sse_idx: conf.find("location /api/")]
        assert "proxy_buffering off" in sse_block
        assert "proxy_read_timeout 3600s" in sse_block

    def test_health_endpoints_passthrough(self, conf):
        """/live /ready /health — проксируются (честный 503 passthrough)."""
        assert r"^/(live|ready|health)$" in conf

    def test_airgap_no_external_dns(self, conf):
        """DNS только Docker embedded resolver; никаких внешних имён."""
        assert "resolver 127.0.0.11" in conf
        for forbidden in ("resolver 8.8.8.8", "resolver 1.1.1.1"):
            assert forbidden not in conf

    def test_ingest_body_limit_raised(self, conf):
        """Ingest-пейлоады больше nginx-дефолта 1m → 413 был бы неизбежен."""
        assert "client_max_body_size" in conf

    def test_spa_fallback_preserved(self, conf):
        """React Router: try_files → index.html."""
        assert "try_files $uri $uri/ /index.html" in conf


class TestCaddyCanonicalEdge:
    """Caddy — канонический внешний edge; SSE-семантика не нарушена."""

    @pytest.fixture(scope="class")
    def caddyfile(self) -> str:
        return _read("services/Caddyfile")

    def test_sse_flush_immediate(self, caddyfile):
        assert "flush_interval -1" in caddyfile

    def test_api_rate_limited(self, caddyfile):
        assert "rate_limit" in caddyfile
        assert "handle /api*" in caddyfile

    def test_health_probes_unlimited_before_api(self, caddyfile):
        """Health/metrics идут раньше rate-limited /api* (ordering contract)."""
        assert caddyfile.find("handle /ready") < caddyfile.find("handle /api*")
