"""COS-035: OpenAPI contract verification tests."""
import json
from pathlib import Path

import pytest
import yaml


DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


class TestOpenAPIContractExists:
    def test_json_spec_exists(self):
        path = DOCS_DIR / "cosmo-openapi.json"
        assert path.is_file(), f"Missing: {path}"

    def test_yaml_spec_exists(self):
        path = DOCS_DIR / "cosmo-openapi.yaml"
        assert path.is_file(), f"Missing: {path}"


class TestOpenAPISchemaIntegrity:
    @pytest.fixture(autouse=True)
    def spec(self):
        with open(DOCS_DIR / "cosmo-openapi.json", encoding="utf-8") as f:
            return json.load(f)

    def test_openapi_version(self, spec):
        assert spec["openapi"].startswith("3.")

    def test_info_fields(self, spec):
        info = spec["info"]
        assert info["title"] == "Cosmoport 2.0 API"
        assert "version" in info

    def test_health_endpoints(self, spec):
        paths = spec["paths"]
        assert "/live" in paths
        assert "/ready" in paths
        assert "/health" in paths

    def test_core_resource_paths(self, spec):
        paths = spec["paths"]
        for prefix in ("/api/v1/domains", "/api/v1/apps", "/api/v1/runs",
                        "/api/v1/gates", "/api/v1/releases", "/api/v1/preferences"):
            assert any(p.startswith(prefix) for p in paths), f"Missing prefix: {prefix}"

    def test_sse_stream_path(self, spec):
        paths = spec["paths"]
        stream_paths = [p for p in paths if "stream" in p]
        assert len(stream_paths) >= 1, "SSE stream endpoint missing"

    def test_schemas_count(self, spec):
        schemas = spec.get("components", {}).get("schemas", {})
        assert len(schemas) >= 35, f"Expected >=35 schemas, got {len(schemas)}"


class TestOpenAPINoLeaks:
    """COS-035: OpenAPI-контракт не содержит утечек credentials."""

    @pytest.fixture(autouse=True)
    def spec(self):
        with open(DOCS_DIR / "cosmo-openapi.json", encoding="utf-8") as f:
            return json.load(f)

    def test_no_raw_token_in_schemas(self, spec):
        """Ни в одной схеме нет поля типа `token: squ_...`."""
        schemas = spec.get("components", {}).get("schemas", {})
        for schema_name, schema in schemas.items():
            props = schema.get("properties", {})
            for prop_name, prop_def in props.items():
                # token_ref — OK (Vault reference)
                # но raw_token / access_token / api_key — не должны быть
                if prop_name in ("access_token", "api_key", "api_secret", "private_key"):
                    desc = prop_def.get("description", "")
                    assert False, f"RAW TOKEN in {schema_name}.{prop_name}: {desc}"

    def test_no_raw_token_in_parameters(self, spec):
        """Query-параметры не содержат token/password/secret.

        COS-101: cookie/header — легитимный транспорт auth-канона
        (session_token cookie — canon COS-066/067/068, Authorization
        header — стандарт). Утечка — только query: URL попадает в
        access-логи, историю браузера и referrer. OpenAPI default
        расположения параметра — query, поэтому отсутствие "in" тоже
        трактуем строго.
        """
        forbidden = ("token", "password", "secret")
        for path, methods in spec["paths"].items():
            for method, details in methods.items():
                if not isinstance(details, dict):
                    continue
                for param in details.get("parameters", []):
                    name = str(param.get("name", ""))
                    location = param.get("in", "query")
                    if location in ("cookie", "header"):
                        continue
                    leaked = [w for w in forbidden if w in name.lower()]
                    assert not leaked, (
                        f"Credential param '{name}' ({location}) in "
                        f"{method} {path}: leaks {leaked} into URLs/logs"
                    )

    def test_session_token_is_cookie_only(self, spec):
        """COS-101: session_token в спеке живёт только как cookie.

        Лочит auth-транспорт канона COS-066/067/068: если кто-то
        регенерирует спеку и session_token уедет в query — тест падает
        до попадания утечки в продукты, логирующие URL.
        """
        seen = 0
        for path, methods in spec["paths"].items():
            for method, details in methods.items():
                if not isinstance(details, dict):
                    continue
                for param in details.get("parameters", []):
                    if param.get("name") == "session_token":
                        seen += 1
                        assert param.get("in") == "cookie", (
                            f"session_token must be cookie, got "
                            f"'{param.get('in')}' in {method} {path}"
                        )
        assert seen > 0, "auth canon lost: no session_token cookie params"

    def test_forge_binding_token_ref_is_vault(self, spec):
        """ForgeBinding.token_ref — это Vault-ссылка, с правильным описанием."""
        schemas = spec.get("components", {}).get("schemas", {})
        fb = schemas.get("ForgeBinding")
        if fb:
            token_ref = fb.get("properties", {}).get("token_ref", {})
            desc = token_ref.get("description", "")
            assert "VAULT" in desc.upper() or "секретниц" in desc.lower() or "ссылк" in desc.lower(), (
                f"ForgeBinding.token_ref description must mention Vault: {desc}"
            )


class TestYAMLSchemaValid:
    def test_yaml_parses(self):
        with open(DOCS_DIR / "cosmo-openapi.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert "openapi" in data
        assert "paths" in data