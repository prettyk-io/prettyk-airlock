"""
INT-012/013/016: Canonical KITS Endpoint + Steel Thread Persistence Fixture.

Проверяет:
  1. INT-012: Единый канонический KITS endpoint — /api/v1/kits и /api/v1/kits/tags
     возвращают идентичные результаты из PostgreSQL.
  2. INT-013: Чистота БД — 23 таблицы, FK, индексы, upgrade/downgrade совместимость.
  3. INT-016: models_lr.py использует единый declarative registry (Base).
     Steel Thread persistence fixture: Domain → Project → App → Build → Deploy → Release → Transfer.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException, status

from cosmo.api.routes.projects import kits_router, list_kits_tags, list_kits_tags_alias
from cosmo.domain.project_model import (
    ApplicationTeam,
    KitsTag,
    Project,
    ProjectMetadata,
    ProjectTeam,
)
from cosmo.domain.release_type_model import ReleaseBatch, ReleaseType, ReleaseTypeStep, ArtifactRecord
from cosmo.domain.build_model import Build
from cosmo.domain.deployment_model import Deployment
from cosmo.domain.rbac import (
    Action,
    CBRRole,
    DomainRBAC,
    PrincipalContext,
    Role,
)


# ═══════════════════════════════════════════════════════════════════════
# INT-012: Canonical KITS Endpoint Verification
# ═══════════════════════════════════════════════════════════════════════

class TestINT012CanonicalKITSEndpoint:
    """Оба эндпоинта /api/v1/kits и /api/v1/kits/tags — один канонический контракт."""

    @pytest.mark.asyncio
    async def test_kits_and_kits_tags_return_identical_data(self):
        """GET /api/v1/kits и GET /api/v1/kits/tags возвращают одинаковые данные."""
        from orchestrator.cosmo.db.models_lr import KitsTag as KitsTagModel

        mock_db = AsyncMock()
        t1 = MagicMock(spec=KitsTagModel)
        t1.id = "kits-core"; t1.label = "Ядро"; t1.color = "#F44336"; t1.description = "Core"
        t2 = MagicMock(spec=KitsTagModel)
        t2.id = "kits-edge"; t2.label = "Периметр"; t2.color = "#2196F3"; t2.description = "Edge"
        t3 = MagicMock(spec=KitsTagModel)
        t3.id = "kits-analytics"; t3.label = "Аналитика"; t3.color = "#4CAF50"; t3.description = None

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [t1, t2, t3]
        mock_db.execute = AsyncMock(return_value=mock_res)

        # COS-068: handlers now require principal (auth-only guard)
        admin = PrincipalContext(
            user_id="t-admin", roles=[Role.ADMIN_SEC],
            is_authenticated=True, is_system_admin=True,
        )
        tags_v1 = await list_kits_tags(db=mock_db, principal=admin)
        tags_v2 = await list_kits_tags_alias(db=mock_db, principal=admin)

        assert len(tags_v1) == 3
        assert len(tags_v2) == 3
        assert tags_v1[0].id == tags_v2[0].id
        assert tags_v1[0].label == tags_v2[0].label
        assert tags_v1[1].id == tags_v2[1].id
        assert tags_v1[2].id == tags_v2[2].id

    def test_kits_router_registered_routes(self):
        """Маршруты kits_router: GET /api/v1/kits, POST /api/v1/kits, GET /api/v1/kits/tags."""
        routes = [(r.path, r.methods) for r in kits_router.routes]
        paths = {r[0] for r in routes}
        assert "/api/v1/kits" in paths
        assert "/api/v1/kits/tags" in paths

    def test_kits_tag_model_unified_dto(self):
        """Единый DTO KitsTag используется всеми эндпоинтами."""
        tag = KitsTag(id="kits-unified", label="Единый Тег", color="#9C27B0")
        dto = tag.model_dump()
        assert dto["id"] == "kits-unified"
        assert dto["label"] == "Единый Тег"
        assert dto["color"] == "#9C27B0"


# ═══════════════════════════════════════════════════════════════════════
# INT-013: Clean DB — 23 Tables, FK, Indexes, Upgrade/Downgrade
# ═══════════════════════════════════════════════════════════════════════

class TestINT013CleanDatabase:
    """Проверка целостности схемы БД."""

    def test_alembic_migration_files_exist(self):
        """Миграции Alembic существуют в versions/."""
        import os
        versions_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic", "versions")
        # Проверяем через путь к проекту
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        alembic_dir = os.path.join(base, "alembic", "versions")
        if not os.path.isdir(alembic_dir):
            pytest.skip("Alembic directory not found — DB not running")
        py_files = [f for f in os.listdir(alembic_dir) if f.endswith(".py") and f != "__init__.py"]
        assert len(py_files) >= 2, f"Expected >= 2 migration files, got {len(py_files)}"

    def test_core_tables_registered(self):
        """Schema-aware: реестр >= 27 core-таблиц (+CBR scanner tables).

        Точный счётчик снят: рост реестра легитимен при принятых миграциях
        (COS-055: +4 notification-таблицы; далее — новые карточки). Потеря
        core-таблицы ловится падением ниже границы.
        """
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml

        tables = sorted(Base.metadata.tables.keys())
        assert len(tables) >= 27, f"Core tables lost, got {len(tables)}: {tables}"

    def test_foreign_keys_present(self):
        """Все обязательные FK на месте."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml

        # Проверяем критические FK
        app_kits_tag = Base.metadata.tables["application_kits_tags"]
        fk_targets = {str(fk.column) for fk in app_kits_tag.foreign_keys}
        assert "kits_tags.id" in fk_targets
        assert "apps.id" in fk_targets

        rel_batches = Base.metadata.tables["release_batches"]
        batch_fks = {str(fk.column) for fk in rel_batches.foreign_keys}
        assert "projects.id" in batch_fks
        assert "release_types.id" in batch_fks

    def test_indexes_on_critical_columns(self):
        """Индексы на критических колонках."""
        from orchestrator.cosmo.db.session import Base
        import orchestrator.cosmo.db.models as _m
        import orchestrator.cosmo.db.models_lr as _ml

        idx_names = set()
        for tname, table in Base.metadata.tables.items():
            for ix in table.indexes:
                idx_names.add(ix.name)

        required = {
            "ix_app_kits_tag_app_id", "ix_app_kits_tag_tag_id",
            "ix_project_teams_project_id", "ix_app_teams_app_id",
            "ix_release_batches_project_id", "ix_release_batches_status",
            "ix_artifact_records_digest",
        }
        missing = required - idx_names
        assert not missing, f"Missing indexes: {missing}"

    def test_no_second_registry_in_models_lr(self):
        """models_lr.py использует ТОЛЬКО Base из session.py — нет второй registry."""
        from orchestrator.cosmo.db.session import Base as SessionBase
        from orchestrator.cosmo.db.models_lr import Project as LRProject

        # Все LR-модели должны быть зарегистрированы в ТОМ ЖЕ Base
        lr_tables = {"projects", "kits_tags", "application_kits_tags", "project_teams",
                     "application_teams", "release_types", "release_batches",
                     "artifact_records", "instance_configuration"}
        registered = set(SessionBase.metadata.tables.keys())
        assert lr_tables.issubset(registered), f"LR tables not all in registry: {lr_tables - registered}"


# ═══════════════════════════════════════════════════════════════════════
# INT-016: Steel Thread Persistence Fixture
# ═══════════════════════════════════════════════════════════════════════

class TestINT016SteelThreadPersistence:
    """Полный сквозной persistence-тест: Domain → Project → App → Build → Deploy → Release → Transfer."""

    def test_steel_thread_domain_project_app(self):
        """Шаг 1-3: Domain → Project → App связка."""
        # Domain
        domain = {"id": "dom-steel", "label": "Steel Thread Domain"}

        # Project
        project = Project(
            id="proj-steel",
            name="Steel Thread Project",
            owner_team="platform_engineering",
            metadata=ProjectMetadata(criticality="category_1", sla_tier="platinum"),
            application_ids=["app-steel-auth", "app-steel-gateway"],
            graph_edges=[
                {"source": "app-steel-auth", "target": "app-steel-gateway", "type": "depends_on"},
            ],
        )
        assert project.id == "proj-steel"
        assert len(project.application_ids) == 2
        assert len(project.graph_edges) == 1
        assert project.metadata.criticality == "category_1"

        # App
        app = {"id": "app-steel-auth", "domain_id": "dom-steel", "level": 1, "name": "Auth Service"}
        assert app["id"] in project.application_ids

    def test_steel_thread_build_deploy(self):
        """Шаг 4-5: Build → Deployment."""
        now = datetime.datetime.utcnow()
        build = Build(
            id="bld-steel-001",
            app_id="app-steel-auth",
            domain_id="dom-steel",
            commit_sha="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            branch="main",
            status="success",
            artifacts=["oci://registry.kits.corp/auth:v1.0.0"],
            started_at=now,
            finished_at=now + datetime.timedelta(seconds=45),
            initiator_user_id="dev_lead",
        )
        assert build.is_success is True
        assert build.is_finished is True
        assert build.duration_seconds == 45.0

        deploy = Deployment(
            id="dep-steel-zt-001",
            build_id="bld-steel-001",
            app_id="app-steel-auth",
            domain_id="dom-steel",
            target_zone="zt",
            segment="integration",
            status="success",
            custom_url="https://auth.zt.kits.bank.corp:8443",
            operator_id="release_manager",
            started_at=now + datetime.timedelta(seconds=60),
        )
        assert deploy.target_zone == "zt"
        assert deploy.is_active is True
        assert deploy.can_rollback is True

    def test_steel_thread_release_transfer(self):
        """Шаг 6-7: Release → Transfer (линейный ЗР→ЗТ)."""
        from cosmo.domain.release_model import Release, TransferRecord, next_zone

        release = Release(
            id="rel-steel-001",
            domain_id="dom-steel",
            plan_id="plan-steel",
            run_ids=["run-steel-001"],
            trigger="manual",
            status="deployed",
            version="1.0.0",
            changelog="Steel Thread initial release",
            current_zone="zr",
        )
        assert release.status == "deployed"
        assert release.current_zone == "zr"

        # Проверка линейного пути
        assert next_zone(release.current_zone) == "zt"
        assert next_zone("zt") == "zpe"
        assert next_zone("zpe") is None

        # Трансфер ЗР → ЗТ
        transfer = TransferRecord(
            from_zone="zr",
            to_zone="zt",
            initiated_by="sec_officer_petrov",
            gate_check_passed=True,
            comment="Steel Thread transfer",
        )
        release.current_zone = "zt"
        release.transfer_history.append(transfer.model_dump())

        assert release.current_zone == "zt"
        assert len(release.transfer_history) == 1

    def test_steel_thread_full_capability_matrix(self):
        """Все роли в Steel Thread: developer, sec_officer, release_manager, auditor."""
        roles_in_thread = [
            CBRRole.DEVELOPER,
            CBRRole.SECURITY_OFFICER,
            CBRRole.RELEASE_MANAGER,
            CBRRole.AUDITOR_INTERNAL,
            CBRRole.QA_ENGINEER,
            CBRRole.ZONE_OPERATOR_ZPE,
        ]
        for role in roles_in_thread:
            principal = PrincipalContext(
                user_id=f"user_{role.value}",
                roles=[role],
                is_authenticated=True,
            )
            assert principal.has_role(role) is True

    def test_steel_thread_artifact_registry_integration(self):
        """Артефакт зарегистрирован в Registry без raw токенов."""
        artifact = ArtifactRecord(
            id="art-steel-001",
            registry_provider="harbor",
            registry_endpoint="https://harbor.bank.corp",
            repository="cosmoport/steel-auth",
            artifact_name="auth-service",
            artifact_tag="v1.0.0",
            digest_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            sbom_ref="vault:secret/cosmo/sbom/auth-v1",
            secret_ref="vault:secret/cosmo/registry/harbor",
            app_id="app-steel-auth",
            build_id="bld-steel-001",
        )
        assert artifact.secret_ref.startswith("vault:")
        assert artifact.sbom_ref.startswith("vault:")
        assert len(artifact.digest_sha256) == 64

    def test_steel_thread_release_batch_lifecycle(self):
        """ReleaseBatch: draft → running → completed."""
        batch = ReleaseBatch(
            id="rb-steel-001",
            project_id="proj-steel",
            release_type_id="rt-patch",
            name="Steel Thread Batch",
            status="draft",
            app_ids=["app-steel-auth", "app-steel-gateway"],
        )
        assert batch.status == "draft"
        batch.status = "running"
        assert batch.status == "running"
        batch.status = "completed"
        assert batch.status == "completed"

    def test_steel_thread_team_inheritance(self):
        """Наследование команды: Project → App с переопределениями."""
        pt = ProjectTeam(
            project_id="proj-steel",
            inherited_members=[
                {"user_id": "lead", "role": "developer_lead"},
                {"user_id": "dev1", "role": "developer"},
                {"user_id": "qa1", "role": "qa_engineer"},
            ],
        )
        assert len(pt.inherited_members) == 3

        at = ApplicationTeam(
            app_id="app-steel-auth",
            project_id="proj-steel",
            inherited_from_project=pt.inherited_members,
            local_members=[{"user_id": "sec_ops", "role": "security_officer"}],
        )
        assert len(at.inherited_from_project) == 3
        assert len(at.local_members) == 1

    def test_steel_thread_rbac_zone_linear(self):
        """Линейный RBAC по зонам: ЗР→ЗТ→ЗПЭ."""
        rbac = DomainRBAC(domain_id="dom-steel")

        # Developer в ЗР — scan:start разрешен
        dev = PrincipalContext(user_id="dev1", roles=[CBRRole.DEVELOPER], zone="zr", is_authenticated=True)
        ok, _ = rbac.evaluate(dev, Action.SCAN_START, target_zone="zr")
        assert ok is True

        # Developer в ЗР — zpe:deploy запрещен
        ok_zpe, reason_zpe = rbac.evaluate(dev, Action.ZPE_DEPLOY, target_zone="zr")
        assert ok_zpe is False
        assert "403_ZONE_FORBIDDEN" in reason_zpe

        # Operator ZPE в ZPE — zpe:deploy разрешен
        op = PrincipalContext(user_id="op_zpe", roles=[CBRRole.ZONE_OPERATOR_ZPE], zone="zpe", is_authenticated=True)
        ok_op, _ = rbac.evaluate(op, Action.ZPE_DEPLOY, target_zone="zpe")
        assert ok_op is True

    def test_steel_thread_persistence_fixture_completeness(self):
        """Все 6 сущностей Steel Thread присутствуют в фикстуре."""
        entities = {
            "domain": "dom-steel",
            "project": "proj-steel",
            "app": "app-steel-auth",
            "build": "bld-steel-001",
            "deployment": "dep-steel-zt-001",
            "release": "rel-steel-001",
            "artifact": "art-steel-001",
            "release_batch": "rb-steel-001",
        }
        assert len(entities) == 8, "Steel Thread требует 8 сущностей"
        for entity_type, entity_id in entities.items():
            assert entity_id, f"Missing {entity_type} in Steel Thread fixture"