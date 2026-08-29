"""COS-008: Тесты Woodpecker ExecutionAdapter."""
import pytest
from cosmo.adapters.execution_woodpecker import (
    JobStatus, WoodpeckerAdapter,
)


class TestJobStatus:
    def test_all_statuses(self):
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.SUCCESS.value == "success"
        assert JobStatus.FAILURE.value == "failure"
        assert JobStatus.KILLED.value == "killed"
        assert JobStatus.ERROR.value == "error"


class TestPipelineYaml:
    def test_empty_batch(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {"bricks": []}
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "pipeline:" in yaml_str
        assert "steps:" in yaml_str

    def test_single_brick(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {
                    "name": "SAST Scan",
                    "definition": {
                        "image": "sonarsource/sonar-scanner-cli:latest",
                        "commands": ["sonar-scanner -Dsonar.host.url=http://sonar:9000"],
                    },
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "SAST Scan" in yaml_str
        assert "sonarsource/sonar-scanner-cli:latest" in yaml_str
        assert "commands:" in yaml_str

    def test_multiple_bricks_with_deps(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {"name": "Build", "definition": {"image": "node:20", "commands": ["npm run build"]}},
                {
                    "name": "Test",
                    "definition": {"image": "node:20", "commands": ["npm test"]},
                    "depends_on": ["Build"],
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "Build" in yaml_str
        assert "Test" in yaml_str

    def test_with_environment(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {
                    "name": "Deploy",
                    "definition": {
                        "image": "alpine:latest",
                        "commands": ["echo $ENV"],
                        "inputs": {"ENV": "production", "REGION": "eu-west-1"},
                    },
                },
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        assert "environment:" in yaml_str
        assert "ENV" in yaml_str
        assert "production" in yaml_str

    def test_yaml_is_valid(self):
        adapter = WoodpeckerAdapter("http://woodpecker:8000", "token")
        batch = {
            "bricks": [
                {"name": "Step", "definition": {"image": "alpine:latest", "commands": ["echo hi"]}},
            ],
        }
        yaml_str = adapter.generate_pipeline_yaml(batch)
        import yaml
        parsed = yaml.safe_load(yaml_str)
        assert parsed is not None
        assert "pipeline" in parsed or "steps" in parsed


class TestEnvVarFallback:
    def test_default_url(self, monkeypatch):
        """Без COSMO_WOODPECKER_URL используется http://woodpecker:8000."""
        monkeypatch.delenv("COSMO_WOODPECKER_URL", raising=False)
        adapter = WoodpeckerAdapter(token="t")
        assert "woodpecker" in adapter._base

    def test_env_var_override(self, monkeypatch):
        """COSMO_WOODPECKER_URL переопределяет URL."""
        monkeypatch.setenv("COSMO_WOODPECKER_URL", "https://ci.cosmo.local")
        adapter = WoodpeckerAdapter(token="t")
        assert adapter._base == "https://ci.cosmo.local"

    def test_explicit_arg_wins(self, monkeypatch):
        """Явный base_url имеет приоритет над env."""
        monkeypatch.setenv("COSMO_WOODPECKER_URL", "https://ci.cosmo.local")
        adapter = WoodpeckerAdapter("http://custom:9000", "t")
        assert adapter._base == "http://custom:9000"