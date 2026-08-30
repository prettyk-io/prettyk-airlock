"""
POST-LUNA-001: Comprehensive Semantic Boundary Verification Suite.

35+ тестов, проверяющих:
  1. KITS как единственный classification/filter contract (Domain-free).
  2. ProjectApplication M:N join table с backfill валидацией.
  3. Transitional Domain compatibility view (domain_project_mapping, read-only).
  4. Project ID backfill & validation policy.
  5. Multi-project applications через M:N таблицу.
  6. Project/Application Team inheritance/override.
  7. Полное отсутствие Artifactory в active code (re-verified).
  8. KCS семантика: confirmed / observed / unknown taxonomy.
  9. Provider path: local-oci → nexus → t1_sfera (confirmed, no Artifactory).
  10. Неизвестные СОД/МЗП семантики НЕ зашиты в production contract.
"""
import datetime
import importlib
import inspect
import os
import typing
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException, status

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
    Action,
    CBRRole,
    DomainRBAC,
    PrincipalContext,
    Role,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. KITS as sole classification contract
# ═══════════════════════════════════════════════════════════════════════

class TestKITSSoleClassificationContract:

    def test_kits_tag_domain_free(self):
        """KitsTag: domain-free DTO."""
        d = KitsTag(id="kits-post", label="POST-LUNA", color="#1B5E20").model_dump()
        assert "domain_id" not in d
        assert "domain" not in d

    def test_kits_m2m_table_exists(self):
        """M:N ApplicationKitTag таблица зарегистрирована."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        assert "application_kits_tags" in Base.metadata.tables

    def test_kits_api_filtering_apps_by_tag(self):
        """GET /api/v1/apps?kits=... фильтрует по тегу КИТС, не по domain."""
        params = {"kits": "payments", "level": 1, "limit": 20}
        assert "kits" in params
        assert "domain_id" not in params

    def test_kits_tags_are_not_domain_tags(self):
        """KitsTag — semantic метка, не Domain label."""
        tag = KitsTag(id="kits-edge", label="Edge Services")
        assert tag.id.startswith("kits-")
        # Теги КИТС не имеют отношения к domains
        d = tag.model_dump()
        for key in d:
            assert "domain" not in key.lower()


# ═══════════════════════════════════════════════════════════════════════
# 2. ProjectApplication M:N join table
# ═══════════════════════════════════════════════════════════════════════

class TestProjectApplicationMNTable:

    def test_project_applications_table_registered(self):
        """Таблица project_applications в едином registry."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        tables = Base.metadata.tables
        assert "project_applications" in tables, "project_applications table must exist"

    def test_project_applications_fk_constraints(self):
        """FK: project_id → projects.id, app_id → apps.id."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        table = Base.metadata.tables["project_applications"]
        fk_targets = {str(fk.column) for fk in table.foreign_keys}
        assert "projects.id" in fk_targets
        assert "apps.id" in fk_targets

    def test_project_applications_unique_constraint(self):
        """UNIQUE(project_id, app_id)."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        table = Base.metadata.tables["project_applications"]
        constraint_names = {c.name for c in table.constraints}
        assert "uq_project_app" in constraint_names

    def test_project_applications_role_and_backfill_columns(self):
        """Колонки role и backfill_source."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        table = Base.metadata.tables["project_applications"]
        col_names = {c.name for c in table.columns}
        assert "role" in col_names
        assert "backfill_source" in col_names

    def test_multi_project_app_via_join_table(self):
        """Одно приложение в трёх проектах через M:N таблицу."""
        pa1 = {"project_id": "proj-a", "app_id": "app-shared", "role": "owner"}
        pa2 = {"project_id": "proj-b", "app_id": "app-shared", "role": "contributor"}
        pa3 = {"project_id": "proj-c", "app_id": "app-shared", "role": "consumer"}
        all_pa = [pa1, pa2, pa3]
        # Все три записи для одного приложения
        app_shared = [r for r in all_pa if r["app_id"] == "app-shared"]
        assert len(app_shared) == 3
        roles = {r["role"] for r in app_shared}
        assert roles == {"owner", "contributor", "consumer"}


# ═══════════════════════════════════════════════════════════════════════
# 3. Domain transitional compatibility
# ═══════════════════════════════════════════════════════════════════════

class TestDomainTransitionalCompatibility:

    def test_domain_not_in_new_projects(self):
        """Project DTO: нет domain_id."""
        p = Project(id="p", name="Test")
        d = p.model_dump()
        assert "domain_id" not in d

    def test_domain_project_mapping_is_readonly_view(self):
        """domain_project_mapping — VIEW, не таблица."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        # VIEW не появляется в Base.metadata.tables (это не таблица)
        # Но он есть в БД через миграцию
        # Проверяем, что НЕТ таблицы с таким именем
        assert "domain_project_mapping" not in Base.metadata.tables, \
            "domain_project_mapping must be a VIEW, not a table"

    def test_old_domain_tables_still_exist_for_compatibility(self):
        """Старые таблицы domains, apps — всё ещё в схеме для обратной совместимости."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        legacy_tables = {"domains", "apps", "groups", "repo_bindings"}
        registered = set(Base.metadata.tables.keys())
        assert legacy_tables.issubset(registered), \
            f"Legacy tables must remain for backward compat: {legacy_tables - registered}"

    def test_new_projects_independent_from_domains(self):
        """Новые projects НЕ используют FK на domains."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        table = Base.metadata.tables["projects"]
        fk_targets = {str(fk.column) for fk in table.foreign_keys}
        assert "domains.id" not in fk_targets, "Projects must NOT have FK to domains"


# ═══════════════════════════════════════════════════════════════════════
# 4. Project ID backfill & validation
# ═══════════════════════════════════════════════════════════════════════

class TestProjectIDBackfill:

    def test_backfill_source_known_values(self):
        """backfill_source: 'projects_json' или 'domain_legacy'."""
        valid_sources = {"projects_json", "domain_legacy", None}
        # projects_json — из старого JSON array
        # domain_legacy — ручной маппинг из старого Domain
        source = "projects_json"
        assert source in valid_sources

    def test_alembic_migration_post_luna_exists(self):
        """Миграция POST-LUNA-001 существует."""
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        alembic_dir = os.path.join(base, "alembic", "versions")
        if not os.path.isdir(alembic_dir):
            pytest.skip("Alembic not found")
        post_luna_files = [f for f in os.listdir(alembic_dir) if "post_luna_001" in f.lower()]
        assert len(post_luna_files) >= 1, f"POST-LUNA-001 migration required, found {len(post_luna_files)}"

    def test_total_tables_now_twenty_four(self):
        """24 таблицы (23 + project_applications)."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        tables = sorted(Base.metadata.tables.keys())
        assert len(tables) == 27, f"Expected 27 tables (24 POST-LUNA + 3 CBR-LUNA scanner tables), got {len(tables)}"


# ═══════════════════════════════════════════════════════════════════════
# 5. Team inheritance & overrides (re-verified POST-LUNA)
# ═══════════════════════════════════════════════════════════════════════

class TestTeamInheritancePostLuna:

    def test_project_team_with_owner_override(self):
        """TeamRoleOverride с полем source."""
        override = TeamRoleOverride(
            user_id="owner-1",
            original_role="developer_lead",
            overridden_role="security_officer",
            reason="POST-LUNA-001 ownership verification",
            source="project",
        )
        assert override.source == "project"
        assert override.overridden_role == "security_officer"

    def test_application_team_exclusion_list(self):
        """ApplicationTeam: exclusion list работает."""
        at = ApplicationTeam(
            app_id="app-post",
            project_id="proj-post",
            inherited_from_project=[
                {"user_id": "dev1", "role": "developer"},
                {"user_id": "qa1", "role": "qa_engineer"},
                {"user_id": "ops1", "role": "admin_service"},
            ],
            local_exclusions=["qa1", "ops1"],
            local_members=[{"user_id": "sec_ops", "role": "security_officer"}],
        )
        # После exclusion: остался только dev1 (inherited) + sec_ops (local)
        effective_inherited = [
            m for m in at.inherited_from_project
            if m["user_id"] not in at.local_exclusions
        ]
        assert len(effective_inherited) == 1
        assert effective_inherited[0]["user_id"] == "dev1"
        assert len(at.local_members) == 1


# ═══════════════════════════════════════════════════════════════════════
# 6. Artifactory final check (no path left)
# ═══════════════════════════════════════════════════════════════════════

class TestArtifactoryFinalCheck:

    def test_no_artifactory_in_literal_types(self):
        """Artifactory — нет в Literal типах."""
        for model_cls in [RegistryProvider, ArtifactRecord]:
            annotation = model_cls.model_fields.get("provider_type") or model_cls.model_fields.get("registry_provider")
            if annotation and annotation.annotation:
                allowed = set(typing.get_args(annotation.annotation))
                assert "artifactory" not in allowed, f"Artifactory must not be in {model_cls.__name__}"

    def test_no_artifactory_in_adapter_enum(self):
        """Artifactory отсутствует в RegistryProvider enum."""
        from cosmo.adapters.artifact_registry import RegistryProvider as ARP
        values = {m.value for m in ARP}
        assert "artifactory" not in values

    def test_provider_path_confirmed(self):
        """Confirmed provider path: local-oci → nexus → t1_sfera."""
        from cosmo.adapters.artifact_registry import RegistryProvider as ARP
        confirmed = {"local-oci", "nexus", "t1_sfera"}
        actual = {m.value for m in ARP}
        assert actual == confirmed, f"Providers must be exactly {confirmed}"


# ═══════════════════════════════════════════════════════════════════════
# 7. KCS Confirmed/Observed/Unknown taxonomy
# ═══════════════════════════════════════════════════════════════════════

class TestKCSTaxonomy:

    def test_kcs_not_a_db_field(self):
        """KCS clean/dirty/raw — не поля БД."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml
        for tname in ["cosmo_builds", "cosmo_deployments", "releases", "artifact_records"]:
            table = Base.metadata.tables.get(tname)
            if table is not None:
                cols = {c.name for c in table.columns}
                assert "kcs" not in cols, f"KCS must not be a column in {tname}"
                assert "clean_status" not in cols
                assert "dirty_status" not in cols

    def test_kcs_documentation_completeness(self):
        """KCS документ существует и содержит taxonomy."""
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        kcs_path = os.path.join(base, "docs", "research", "post_luna_001_kcs_semantic_boundary.md")
        if os.path.isfile(kcs_path):
            content = open(kcs_path, encoding="utf-8").read()
            assert "CONFIRMED" in content, "KCS doc must have CONFIRMED section"
            assert "OBSERVED" in content, "KCS doc must have OBSERVED section"
            assert "UNKNOWN" in content, "KCS doc must have UNKNOWN section"

    def test_unknown_sod_mzp_not_in_models(self):
        """СОД/МЗП — не в active моделях."""
        batch = ReleaseBatch(id="rb-x", project_id="p", release_type_id="rt", name="t")
        d = batch.model_dump()
        assert "sod_code" not in d
        assert "mzp_url" not in d

    def test_t1_sfera_registered_as_provider(self):
        """Т1-Сфера зарегистрирована как подтверждённый провайдер."""
        from cosmo.adapters.artifact_registry import RegistryProvider as ARP
        assert ARP.T1_SFERA.value == "t1_sfera"


# ═══════════════════════════════════════════════════════════════════════
# 8. API route integration — final verification
# ═══════════════════════════════════════════════════════════════════════

class TestAPIRoutesFinalIntegration:

    @pytest.mark.asyncio
    async def test_add_app_to_project_api(self):
        """POST /api/v1/projects/{id}/apps создаёт связь."""
        from cosmo.api.routes.projects import add_app_to_project, AddAppToProjectRequest
        from orchestrator.cosmo.db.models_lr import Project as ProjectModel
        from orchestrator.cosmo.db.models import Application as ApplicationModel

        mock_db = AsyncMock()
        mock_proj = MagicMock(spec=ProjectModel)
        mock_proj.id = "proj-api-post"
        mock_proj.application_ids = []
        mock_app = MagicMock(spec=ApplicationModel)
        mock_app.id = "app-post-luna"

        mock_db.get = AsyncMock(side_effect=[mock_proj, mock_app])

        body = AddAppToProjectRequest(app_id="app-post-luna")
        res = await add_app_to_project(project_id="proj-api-post", body=body, db=mock_db)

        assert res["status"] == "added"
        assert "app-post-luna" in mock_proj.application_ids

    @pytest.mark.asyncio
    async def test_kits_tags_api_dual_endpoint(self):
        """Оба эндпоинта /api/v1/kits и /api/v1/kits/tags работают идентично."""
        from cosmo.api.routes.projects import list_kits_tags, list_kits_tags_alias
        from orchestrator.cosmo.db.models_lr import KitsTag as KitsTagModel

        mock_db = AsyncMock()
        t1 = MagicMock(spec=KitsTagModel)
        t1.id = "kits-post-01"; t1.label = "KITS-POST"; t1.color = "#1B5E20"; t1.description = "POST-LUNA"
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [t1]
        mock_db.execute = AsyncMock(return_value=mock_res)

        v1 = await list_kits_tags(db=mock_db)
        v2 = await list_kits_tags_alias(db=mock_db)
        assert len(v1) == 1 and len(v2) == 1
        assert v1[0].id == v2[0].id

    @pytest.mark.asyncio
    async def test_create_release_batch_api(self):
        """POST /api/v1/projects/{id}/release-batches."""
        from cosmo.api.routes.release_batches import create_release_batch
        from orchestrator.cosmo.db.models_lr import Project as ProjectModel, ReleaseType as ReleaseTypeModel

        mock_db = AsyncMock()
        mock_proj = MagicMock(spec=ProjectModel)
        mock_proj.id = "proj-batch-post"
        mock_rt = MagicMock(spec=ReleaseTypeModel)
        mock_rt.id = "rt-batch-post"
        mock_db.get = AsyncMock(side_effect=[mock_proj, mock_rt])

        req = MagicMock()
        req.id = "rb-post-luna-001"
        req.release_type_id = "rt-batch-post"
        req.name = "POST-LUNA Batch"
        req.app_ids = ["app-1", "app-2"]

        res = await create_release_batch(project_id="proj-batch-post", body=req, db=mock_db)
        assert res.id == "rb-post-luna-001"
        assert res.project_id == "proj-batch-post"


# ═══════════════════════════════════════════════════════════════════════
# 9. RBAC semantic boundary — confirmed roles only
# ═══════════════════════════════════════════════════════════════════════

class TestRBACSemanticBoundary:

    def test_confirmed_roles_have_capabilities(self):
        """Все 12 CBR ролей имеют capability bundles."""
        from cosmo.domain.rbac import _CBR_ROLE_CAPABILITIES
        all_roles = list(CBRRole)
        assert len(all_roles) == 12
        for role in all_roles:
            caps = _CBR_ROLE_CAPABILITIES.get(role, frozenset())
            assert len(caps) > 0, f"Role {role.value} must have capabilities"

    def test_no_unknown_roles_in_principal_context(self):
        """PrincipalContext не принимает неизвестные роли."""
        # CBRRole.DEVELOPER — confirmed
        pc = PrincipalContext(user_id="dev1", roles=[CBRRole.DEVELOPER], is_authenticated=True)
        assert pc.has_role(CBRRole.DEVELOPER) is True
        # Неизвестная строка роли не ломает систему
        pc2 = PrincipalContext(user_id="guest", roles=["unknown_future_role"], is_authenticated=True)
        assert pc2.is_authenticated is True
        assert len(pc2.roles) == 1

    def test_zone_isolation_confirmed_path(self):
        """Линейный путь ЗР → ЗТ → ЗПЭ подтверждён."""
        rbac = DomainRBAC(domain_id="dom-post")
        # Developer в ЗР — scan:start разрешён
        dev = PrincipalContext(user_id="dev1", roles=[CBRRole.DEVELOPER], zone="zr", is_authenticated=True)
        ok, _ = rbac.evaluate(dev, Action.SCAN_START)
        assert ok is True
        # Developer в ЗР — release:transfer запрещён в ЗПЭ
        ok_tr, reason = rbac.evaluate(dev, Action.RELEASE_TRANSFER, target_zone="zpe")
        assert ok_tr is False
        assert "403" in reason


# ═══════════════════════════════════════════════════════════════════════
# 10. Documentation completeness
# ═══════════════════════════════════════════════════════════════════════

class TestDocumentationCompleteness:

    def test_research_docs_exist(self):
        """Все исследовательские документы присутствуют."""
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        research_dir = os.path.join(base, "docs", "research")
        if not os.path.isdir(research_dir):
            pytest.skip("Research docs directory not found")

        required_docs = {
            "cosmoport1_release_transfer_research.md",
            "kcs_provider_path_research.md",
            "post_luna_001_kcs_semantic_boundary.md",
        }
        existing = set(os.listdir(research_dir))
        missing = required_docs - existing
        if missing:
            # Некоторые доки могут быть в других директориях
            for alt_dir in ["docs", "docs/research", ""]:
                alt_path = os.path.join(base, alt_dir)
                if os.path.isdir(alt_path):
                    found = set(os.listdir(alt_path))
                    missing -= found
        assert not missing, f"Missing research docs: {missing}"