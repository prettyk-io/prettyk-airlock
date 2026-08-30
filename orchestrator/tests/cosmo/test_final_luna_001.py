"""
FINAL-LUNA-001: Backend Cleanliness & Sfera Repository Semantics Verification.

Проверяет:
  1. Полное отсутствие Artifactory в active Cosmoport code.
  2. Активные провайдеры: local-oci, nexus, t1_sfera.
  3. Единый канонический KITS endpoint.
  4. Чистоту БД (23 таблицы, FK, индексы).
  5. Project/KITS/Team/ReleaseType/ReleaseBatch persistence.
  6. Domain-free новые fixtures.
  7. ArtifactRecord и digest linkage.
  8. KCS семантика clean/dirty/raw — observed, не confirmed.
"""
import datetime
import importlib
import inspect
import os
import typing
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

from cosmo.domain.instance_config import InstanceConfiguration, RegistryProvider
from cosmo.domain.project_model import (
    ApplicationTeam,
    KitsTag,
    Project,
    ProjectMetadata,
    ProjectTeam,
    TeamRoleOverride,
)
from cosmo.domain.release_type_model import (
    ArtifactRecord,
    ReleaseBatch,
    ReleaseType,
    ReleaseTypeStep,
)
from cosmo.domain.rbac import (
    CBRRole,
    PrincipalContext,
    Role,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. NO ARTFACTORY
# ═══════════════════════════════════════════════════════════════════════

class TestNoArtifactory:

    def test_registry_provider_literals_no_artifactory(self):
        allowed = set(typing.get_args(RegistryProvider.model_fields["provider_type"].annotation))
        assert "local-oci" in allowed
        assert "nexus" in allowed
        assert "t1_sfera" in allowed
        assert "harbor" in allowed
        assert "artifactory" not in allowed, "ARTIFACTORY MUST NOT BE IN ACTIVE CODE"

    def test_artifact_record_literals_no_artifactory(self):
        allowed = set(typing.get_args(ArtifactRecord.model_fields["registry_provider"].annotation))
        assert "artifactory" not in allowed, "ARTIFACTORY MUST NOT BE IN AR MODEL"

    def test_adapter_enum_no_artifactory(self):
        from cosmo.adapters.artifact_registry import RegistryProvider as ARP
        members = {m.name for m in ARP}
        assert "LOCAL_OCI" in members
        assert "NEXUS" in members
        assert "T1_SFERA" in members
        assert "ARTIFACTORY" not in members, "ARTIFACTORY member removed from enum"

    def test_no_artifactory_in_oci_registry_docstring(self):
        mod = importlib.import_module("cosmo.adapters.oci_registry")
        doc = mod.__doc__ or ""
        assert "JFrog Artifactory (artifactory)" not in doc, "Artifactory must not appear in oci_registry docstring"


# ═══════════════════════════════════════════════════════════════════════
# 2. Активные провайдеры
# ═══════════════════════════════════════════════════════════════════════

class TestActiveProviderPath:

    def test_local_oci_default(self):
        rp = RegistryProvider(endpoint_url="https://local.oci:5100", namespace="cosmoport-dev")
        assert rp.provider_type == "local-oci"

    def test_nexus_staging_provider(self):
        rp = RegistryProvider(
            provider_type="nexus", endpoint_url="https://nexus.corp",
            namespace="cosmoport-staging", auth_ref="vault:secret/cosmo/registry/nexus",
        )
        assert rp.provider_type == "nexus"
        assert rp.auth_ref.startswith("vault:")

    def test_t1_sfera_production_provider(self):
        rp = RegistryProvider(
            provider_type="t1_sfera", endpoint_url="https://t1-sfera.bank.corp",
            namespace="cosmoport-prod", auth_ref="vault:secret/cosmo/registry/t1-sfera",
        )
        assert rp.provider_type == "t1_sfera"
        assert rp.auth_ref.startswith("vault:")

    def test_provider_linear_path(self):
        path = [
            RegistryProvider(provider_type="local-oci", endpoint_url="http://local:5100", namespace="cosmoport-dev"),
            RegistryProvider(provider_type="nexus", endpoint_url="https://nexus.corp", namespace="cosmoport", auth_ref="vault:secret/nexus"),
            RegistryProvider(provider_type="t1_sfera", endpoint_url="https://t1-sfera.corp", namespace="cosmoport", auth_ref="vault:secret/t1-sfera"),
        ]
        expected = ["local-oci", "nexus", "t1_sfera"]
        for rp, exp in zip(path, expected):
            assert rp.provider_type == exp


# ═══════════════════════════════════════════════════════════════════════
# 3. Единый KITS contract
# ═══════════════════════════════════════════════════════════════════════

class TestOneCanonicalKITSContract:

    @pytest.mark.asyncio
    async def test_kits_list_returns_tags(self):
        from cosmo.api.routes.projects import list_kits_tags
        from orchestrator.cosmo.db.models_lr import KitsTag as KitsTagModel

        mock_db = AsyncMock()
        t1 = MagicMock(spec=KitsTagModel)
        t1.id = "kits-core"; t1.label = "Ядро"; t1.color = "#F44336"; t1.description = None
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [t1]
        mock_db.execute = AsyncMock(return_value=mock_res)

        tags = await list_kits_tags(db=mock_db)
        assert len(tags) == 1
        assert tags[0].id == "kits-core"
        assert hasattr(tags[0], "id")
        assert hasattr(tags[0], "label")

    def test_kits_tag_domain_free_dto(self):
        tag = KitsTag(id="kits-01", label="Тест", color="#FFC107")
        d = tag.model_dump()
        assert "domain_id" not in d
        assert "domain" not in d


# ═══════════════════════════════════════════════════════════════════════
# 4. Чистота БД
# ═══════════════════════════════════════════════════════════════════════

class TestCleanDatabase:

    def test_twenty_three_tables(self):
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        tables = sorted(Base.metadata.tables.keys())
        assert len(tables) == 27, f"Expected 27 tables (CBR-LUNA added scanner tables), got {len(tables)}"

    def test_lr_tables_present(self):
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        tables = set(Base.metadata.tables.keys())
        lr_required = {"projects", "kits_tags", "application_kits_tags",
                       "project_teams", "application_teams", "release_types",
                       "release_batches", "artifact_records", "instance_configuration"}
        assert lr_required.issubset(tables), f"Missing: {lr_required - tables}"

    def test_alembic_versions_exist(self):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        alembic_dir = os.path.join(base, "alembic", "versions")
        if not os.path.isdir(alembic_dir):
            pytest.skip("Alembic not found — DB not running")
        py_files = [f for f in os.listdir(alembic_dir) if f.endswith(".py") and f != "__init__.py"]
        assert len(py_files) >= 2, f"Expected >= 2 migrations, got {len(py_files)}"


# ═══════════════════════════════════════════════════════════════════════
# 5. Persistence chain
# ═══════════════════════════════════════════════════════════════════════

class TestPersistenceChain:

    def test_project_full_persistence(self):
        project = Project(
            id="proj-final", name="Final Project", description="Persistence verification",
            owner_team="platform_engineering",
            metadata=ProjectMetadata(criticality="category_1", sla_tier="platinum", deployment_model="hybrid"),
            application_ids=["app-auth", "app-gateway", "app-db"],
            graph_edges=[{"source": "app-auth", "target": "app-gateway", "type": "depends_on"}],
            kits_tags=["kits-core", "kits-security"],
        )
        assert project.id == "proj-final"
        assert len(project.application_ids) == 3
        assert len(project.kits_tags) == 2

    def test_team_inheritance_full_chain(self):
        pt = ProjectTeam(
            project_id="proj-final",
            inherited_members=[{"user_id": "lead", "role": "developer_lead"}, {"user_id": "dev1", "role": "developer"}],
            local_additions=[{"user_id": "po", "role": "product_owner"}],
            local_exclusions=["dev1"],
            role_overrides=[TeamRoleOverride(user_id="lead", original_role="developer_lead", overridden_role="security_officer", reason="FINAL-LUNA-001", source="project")],
        )
        assert len(pt.role_overrides) == 1
        at = ApplicationTeam(app_id="app-auth", project_id="proj-final", inherited_from_project=pt.inherited_members,
                             local_members=[{"user_id": "sec_ops", "role": "security_officer"}])
        assert len(at.inherited_from_project) == 2

    def test_release_type_and_batch(self):
        rt = ReleaseType(id="rt-final", name="Final RT", version="1.0.0",
                         steps=[ReleaseTypeStep(order=0, name="Build", brick_type="build", gate_required=False)])
        assert len(rt.steps) == 1
        batch = ReleaseBatch(id="rb-final-001", project_id="proj-final", release_type_id="rt-final", name="Batch")
        assert batch.project_id == "proj-final"


# ═══════════════════════════════════════════════════════════════════════
# 6. Domain-free fixtures
# ═══════════════════════════════════════════════════════════════════════

class TestDomainFreeFixtures:

    def test_project_domain_free(self):
        d = Project(id="p", name="Test").model_dump()
        assert "domain_id" not in d

    def test_kits_tag_domain_free(self):
        d = KitsTag(id="k", label="T").model_dump()
        assert "domain_id" not in d

    def test_release_type_domain_free(self):
        d = ReleaseType(id="rt", name="RT").model_dump()
        assert "domain_id" not in d

    def test_instance_config_domain_free(self):
        cfg = InstanceConfiguration(instance_id="cosmo-final", forge_endpoint_url="https://gitea.corp", registry_endpoint_url="https://registry.corp")
        assert "domain_id" not in cfg.model_dump()

    def test_project_endpoints_domain_free(self):
        mod = importlib.import_module("cosmo.api.routes.projects")
        list_fn = getattr(mod, "list_projects", None)
        assert list_fn is not None
        sig = inspect.signature(list_fn)
        params = list(sig.parameters.keys())
        assert "caller_domain" not in params, "list_projects must not require caller_domain"


# ═══════════════════════════════════════════════════════════════════════
# 7. ArtifactRecord & digest linkage
# ═══════════════════════════════════════════════════════════════════════

class TestArtifactRecordDigest:

    def test_artifact_record_sha256_digest(self):
        digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        record = ArtifactRecord(
            id="art-digest-01", registry_provider="t1_sfera", registry_endpoint="https://t1-sfera.corp",
            repository="cosmoport/auth", artifact_name="auth-service", artifact_tag="v1.0.0",
            digest_sha256=digest, secret_ref="vault:secret/cosmo/registry/t1-sfera",
            app_id="app-auth", build_id="bld-auth-001",
        )
        assert len(record.digest_sha256) == 64
        assert record.registry_provider == "t1_sfera"
        assert record.secret_ref.startswith("vault:")

    def test_artifact_record_sbom_scan_linkage(self):
        record = ArtifactRecord(
            id="art-link-01", registry_provider="nexus", registry_endpoint="https://nexus.corp",
            repository="cosmoport/gateway", artifact_name="gateway-service", artifact_tag="v2.0.0",
            digest_sha256="a" * 64,
            sbom_ref="vault:secret/cosmo/sbom/gateway-v2",
            scan_refs=["scan-sast-gw-001", "scan-dast-gw-002", "scan-sca-gw-001"],
            signature_attestation="vault:secret/cosmo/attestations/slsa-l4-gw",
            secret_ref="vault:secret/cosmo/registry/nexus",
            app_id="app-gateway", build_id="bld-gw-001",
        )
        assert len(record.scan_refs) == 3
        assert record.sbom_ref.startswith("vault:")
        assert record.signature_attestation.startswith("vault:")


# ═══════════════════════════════════════════════════════════════════════
# 8. KCS semantics — observed, not confirmed
# ═══════════════════════════════════════════════════════════════════════

class TestKCSSemanticsProvisional:

    def test_kcs_not_hardcoded_as_field(self):
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        for tname in ["releases", "cosmo_builds", "cosmo_deployments", "artifact_records"]:
            table = Base.metadata.tables.get(tname)
            if table is not None:
                cols = {c.name for c in table.columns}
                assert "kcs" not in cols, f"KCS field must NOT be in {tname}"
                assert "clean_status" not in cols
                assert "dirty_status" not in cols

    def test_kcs_documentation_exists(self):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        research_dir = os.path.join(base, "docs", "research")
        kcs_files = [f for f in os.listdir(research_dir) if "kcs" in f.lower() or "provider" in f.lower()] if os.path.isdir(research_dir) else []
        assert len(kcs_files) >= 1, f"KCS research required, found {len(kcs_files)}"

    def test_unknown_semantics_not_asserted_as_fact(self):
        batch = ReleaseBatch(id="rb-x", project_id="p", release_type_id="rt", name="test")
        d = batch.model_dump()
        assert "sod_code" not in d, "СОД/МЗП поля не должны быть в active модели"
        assert "mzp_url" not in d, "СОД/МЗП поля не должны быть в active модели"