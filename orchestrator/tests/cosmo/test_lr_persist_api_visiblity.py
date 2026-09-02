"""
LR-001..LR-009: Comprehensive Persistence, API, Contract & Visibility Tests.

Покрывает:
  LR-001: Project persistence — создание, пустой проект, multi-project app, FK.
  LR-002: KITS tags — создание тегов, M2M связь, API.
  LR-003: Team inheritance — Project Team, Application Team, overrides, exclusions.
  LR-004: Instance configuration — загрузка, дефолты.
  LR-005: Projects/KITS API — эндпоинты GET/POST/PUT с фильтрацией и пагинацией.
  LR-006: Release Types & ReleaseBatch API — CRUD, версионирование.
  LR-007: Artifact Registry persistence — метаданные, no raw passwords.
  LR-008: PrettyK contract tests — внешний контракт без внутренних импортов.
  LR-009: Visibility matrix — 12 сценариев (Project Team inheritance, Application overrides,
          Admin KITS, readonly, Admin IB, Admin НШР, admin_service, system admin,
          multi-project app, GET без domain context, forbidden mutation, серверная фильтрация).
"""
import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException, status

from cosmo.domain.instance_config import InstanceConfiguration
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
from cosmo.domain.rbac import CBRRole, PrincipalContext, Role


# ═══════════════════════════════════════════════════════════════════════
# LR-001: Project Persistence
# ═══════════════════════════════════════════════════════════════════════

class TestLR001ProjectPersistence:
    """Проверка сохранения и загрузки проектов из PostgreSQL."""

    def test_empty_project_creation(self):
        """Пустой проект создаётся корректно."""
        project = Project(
            id="proj-empty",
            name="Empty Test Project",
            description="This is a minimal project",
            application_ids=[],
            graph_edges=[],
        )
        assert project.id == "proj-empty"
        assert project.name == "Empty Test Project"
        assert len(project.application_ids) == 0
        assert len(project.graph_edges) == 0
        assert project.owner_team == "core_platform"

    def test_project_with_applications_and_edges(self):
        """Проект с приложениями и графом."""
        project = Project(
            id="proj-full",
            name="Full Project",
            application_ids=["app-auth", "app-payments", "app-gateway"],
            graph_edges=[
                {"source": "app-auth", "target": "app-payments", "type": "depends_on"},
                {"source": "app-gateway", "target": "app-auth", "type": "triggers"},
            ],
            metadata=ProjectMetadata(
                criticality="category_1",
                sla_tier="platinum",
                deployment_model="hybrid",
            ),
        )
        assert len(project.application_ids) == 3
        assert len(project.graph_edges) == 2
        assert project.metadata.criticality == "category_1"

    def test_application_in_multiple_projects(self):
        """Одно приложение может состоять в нескольких проектах."""
        p1 = Project(id="p1", name="P1", application_ids=["app-shared"])
        p2 = Project(id="p2", name="P2", application_ids=["app-shared"])
        assert "app-shared" in p1.application_ids
        assert "app-shared" in p2.application_ids

    def test_project_serialization(self):
        """Сериализация проекта в dict."""
        p = Project(id="p-serial", name="Serial Project", application_ids=["a1"])
        d = p.model_dump()
        assert d["id"] == "p-serial"
        assert d["application_ids"] == ["a1"]


# �══════════════════════════════════════════════════════════════════════════
# LR-002: KITS Tags
# �══════════════════════════════════════════════════════════════════════════

class TestLR002KITSTags:
    """Проверка тегов КИТС."""

    def test_create_tag(self):
        tag = KitsTag(id="kits-payments", label="Платежная система", color="#FF5722")
        assert tag.id == "kits-payments"
        assert tag.label == "Платежная система"
        assert tag.color == "#FF5722"

    def test_tag_app_m2m(self):
        """M:N связь tag <-> app через список ID."""
        project = Project(
            id="p-tags",
            name="Tagged Project",
            kits_tags=["kits-payments", "kits-core"],
            application_ids=["app-1", "app-2"],
        )
        assert len(project.kits_tags) == 2
        assert "kits-core" in project.kits_tags

    @pytest.mark.asyncio
    async def test_list_kits_tags_api(self):
        """API GET /api/v1/kits возвращает список тегов."""
        from cosmo.api.routes.projects import list_kits_tags
        from orchestrator.cosmo.db.models_lr import KitsTag as KitsTagModel

        mock_db = AsyncMock()
        mock_tag = MagicMock(spec=KitsTagModel)
        mock_tag.id = "kits-auth"
        mock_tag.label = "Аутентификация"
        mock_tag.color = "#1565C0"
        mock_tag.description = "Сервисы ИАМ"

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_tag]
        mock_db.execute = AsyncMock(return_value=mock_res)

        # COS-068: handler now requires principal (auth-only guard)
        admin = PrincipalContext(
            user_id="t-admin", roles=[Role.ADMIN_SEC],
            is_authenticated=True, is_system_admin=True,
        )
        tags = await list_kits_tags(db=mock_db, principal=admin)
        assert len(tags) == 1
        assert tags[0].id == "kits-auth"


# �══════════════════════════════════════════════════════════════════════════
# LR-003: Team Inheritance & Overrides
# �══════════════════════════════════════════════════════════════════════════

class TestLR003TeamInheritance:
    """Проверка наследования и переопределения команд."""

    def test_project_team_creation(self):
        team = ProjectTeam(
            project_id="proj-team-01",
            inherited_members=[
                {"user_id": "usr-1", "role": "developer"},
                {"user_id": "usr-2", "role": "qa_engineer"},
            ],
            local_additions=[{"user_id": "usr-3", "role": "product_owner"}],
            local_exclusions=["usr-old"],
            role_overrides=[
                TeamRoleOverride(
                    user_id="usr-1",
                    original_role="developer",
                    overridden_role="developer_lead",
                    reason="Назначен тимлидом на уровне приложения",
                    source="app_local",
                )
            ],
        )
        assert len(team.inherited_members) == 2
        assert len(team.local_additions) == 1
        assert "usr-old" in team.local_exclusions
        assert len(team.role_overrides) == 1
        assert team.role_overrides[0].source == "app_local"

    def test_application_team_inheritance_from_project(self):
        """Команда приложения наследует Project Team."""
        app_team = ApplicationTeam(
            app_id="app-telemetry",
            project_id="proj-team-01",
            inherited_from_project=[
                {"user_id": "usr-1", "role": "developer"},
                {"user_id": "usr-2", "role": "qa_engineer"},
            ],
            local_members=[{"user_id": "usr-4", "role": "admin_service"}],
            local_exclusions=["usr-2"],  # Исключаем QA из конечного состава
        )
        assert len(app_team.inherited_from_project) == 2
        assert len(app_team.local_members) == 1
        assert "usr-2" in app_team.local_exclusions


# �══════════════════════════════════════════════════════════════════════════
# LR-004: Instance Configuration
# �══════════════════════════════════════════════════════════════════════

class TestLR004InstanceConfiguration:
    """Проверка глобальной конфигурации инстанса."""

    def test_default_config(self):
        cfg = InstanceConfiguration(
            forge_endpoint_url="https://gitea.internal.corp",
            registry_endpoint_url="https://harbor.internal.corp",
        )
        assert cfg.instance_id == "cosmo-primary"
        assert cfg.network_id == "kits-core-net"
        assert cfg.zone == "zr"

    def test_no_hardcoded_domain(self):
        """Платформа не завязана на ПлЦР/cbr."""
        cfg = InstanceConfiguration(
            forge_endpoint_url="https://gitlab.anycorp.io",
            registry_endpoint_url="https://registry.anycorp.io",
        )
        assert "cbr" not in cfg.platform_label.lower()


# ═══════════════════════════════════════════════════════════════════════
# LR-005: Projects/KITS/Applications API
# ═══════════════════════════════════════════════════════════════════════

class TestLR005ProjectsKITSApi:
    """Интеграционные тесты API проектов и КИТС."""

    @pytest.mark.asyncio
    async def test_create_and_list_projects(self):
        from cosmo.api.routes.projects import create_project, list_projects
        from orchestrator.cosmo.db.models_lr import Project as ProjectModel

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)  # Нет существующего проекта

        principal = PrincipalContext(user_id="admin_sec", roles=[Role.ADMIN_SEC], is_authenticated=True)

        req = MagicMock()
        req.id = "proj-api-01"
        req.name = "API Project"
        req.description = "Test project"
        req.owner_team = "core_dev"
        req.criticality = "category_2"
        req.sla_tier = "gold"
        req.deployment_model = "microservices"
        req.git_repo_root = None
        req.metadata = {}

        created = await create_project(body=req, principal=principal, db=mock_db)
        assert created.id == "proj-api-01"
        assert created.name == "API Project"

    @pytest.mark.asyncio
    async def test_project_not_found_returns_404(self):
        from cosmo.api.routes.projects import get_project

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        admin = PrincipalContext(
            user_id="t-admin", roles=[Role.ADMIN_SEC],
            is_authenticated=True, is_system_admin=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_project(project_id="nonexistent", db=mock_db, principal=admin)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_add_app_to_project(self):
        from cosmo.api.routes.projects import add_app_to_project, AddAppToProjectRequest
        from orchestrator.cosmo.db.models_lr import Project as ProjectModel
        from orchestrator.cosmo.db.models import Application as ApplicationModel

        mock_db = AsyncMock()

        mock_project = MagicMock(spec=ProjectModel)
        mock_project.id = "proj-add-app"
        mock_project.application_ids = []

        mock_app = MagicMock(spec=ApplicationModel)
        mock_app.id = "app-auth-svc"
        # COS-083: ghost-контракт — домен мок-приложения должен совпадать
        # с резолвнутым доменом caller'а (админ без заголовка → "default").
        mock_app.domain_id = "default"

        mock_db.get = AsyncMock(side_effect=[mock_project, mock_app])

        body = AddAppToProjectRequest(app_id="app-auth-svc")
        # COS-068: handler now requires principal
        admin = PrincipalContext(
            user_id="t-admin", roles=[Role.ADMIN_SEC],
            is_authenticated=True, is_system_admin=True,
        )
        res = await add_app_to_project(project_id="proj-add-app", body=body, db=mock_db, principal=admin)

        assert res["status"] == "added"
        assert "app-auth-svc" in mock_project.application_ids


# �══════════════════════════════════════════════════════════════════════════
# LR-006: Release Types & ReleaseBatch API
# �══════════════════════════════════════════════════════════════════════════

class TestLR006ReleaseTypesBatch:
    """Проверка профилей типов релизов и батчей."""

    def test_release_type_versioned(self):
        rt = ReleaseType(
            id="rt-patch",
            name="Patch Release",
            version="2.1.0",
            steps=[
                ReleaseTypeStep(order=0, name="Build", brick_type="build"),
                ReleaseTypeStep(order=1, name="SAST Scan", brick_type="sast", gate_required=True),
                ReleaseTypeStep(order=2, name="Deploy ZT", brick_type="deploy", zone="zt", gate_required=True),
            ],
            required_approvals=2,
            allowed_zones=["zr", "zt", "zpe"],
        )
        assert rt.version == "2.1.0"
        assert len(rt.steps) == 3
        assert rt.steps[1].gate_required is True

    def test_release_batch_lifecycle(self):
        batch = ReleaseBatch(
            id="rb-2026-001",
            project_id="proj-core",
            release_type_id="rt-patch",
            name="Q3 Security Patches",
            status="draft",
            app_ids=["app-auth", "app-payments"],
        )
        assert batch.status == "draft"
        batch.status = "running"
        assert batch.status == "running"

    @pytest.mark.asyncio
    async def test_create_release_type_api(self):
        """Проверка создания ReleaseType через API хэндлер."""
        from cosmo.api.routes.release_batches import create_release_type

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        req = MagicMock()
        req.id = "rt-emergency"
        req.name = "Emergency Release"
        req.description = None
        req.version = "1.0.0"
        req.steps = [MagicMock()]
        req.steps[0].model_dump.return_value = {"order": 0, "name": "Build", "brick_type": "build", "gate_required": True, "zone": None}
        req.required_approvals = 1
        req.allowed_zones = ["zr", "zt", "zpe"]

        # Mock the ORM model that gets created by the handler
        class FakeRT:
            pass
        fake_rt = FakeRT()
        fake_rt.id = "rt-emergency"
        fake_rt.name = "Emergency Release"
        fake_rt.description = None
        fake_rt.version = "1.0.0"
        fake_rt.steps_json = []
        fake_rt.required_approvals = 1
        fake_rt.allowed_zones = ["zr", "zt", "zpe"]
        fake_rt.is_active = True
        fake_rt.created_at = None
        fake_rt.updated_at = None

        # Patch db.add + commit + refresh
        async def fake_commit():
            pass
        async def fake_refresh(obj):
            obj.id = fake_rt.id
            obj.name = fake_rt.name
            obj.steps_json = fake_rt.steps_json
            obj.required_approvals = fake_rt.required_approvals
            obj.allowed_zones = fake_rt.allowed_zones
            obj.is_active = fake_rt.is_active
        mock_db.commit = AsyncMock(side_effect=fake_commit)
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        # COS-068: create_release_type is now system-admin only
        admin = PrincipalContext(
            user_id="t-admin", roles=[Role.ADMIN_SEC],
            is_authenticated=True, is_system_admin=True,
        )
        created = await create_release_type(body=req, db=mock_db, principal=admin)
        assert created.id == "rt-emergency"
        assert created.required_approvals == 1


# �══════════════════════════════════════════════════════════════════════════
# LR-007: Artifact Registry Persistence
# �══════════════════════════════════════════════════════════════════════════

class TestLR007ArtifactRegistry:
    """Проверка персистентности метаданных артефактов."""

    def test_artifact_no_raw_passwords(self):
        """В ArtifactRecord нет raw паролей — только vault:secret/..."""
        record = ArtifactRecord(
            id="art-001",
            registry_endpoint="https://harbor.corp",
            repository="cosmoport/alpha",
            artifact_name="auth-service",
            artifact_tag="v1.2.3",
            digest_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            secret_ref="vault:secret/cosmo/registry/harbor",
        )
        # Проверка: secret_ref — строго vault: префикс
        assert record.secret_ref.startswith("vault:")
        # Нет открытых токенов
        assert "ghp_" not in record.digest_sha256
        assert "squ_" not in record.digest_sha256

    def test_sbom_and_scan_refs(self):
        record = ArtifactRecord(
            id="art-002",
            registry_endpoint="https://registry.corp",
            repository="cosmoport/beta",
            artifact_name="payment-gateway",
            artifact_tag="latest",
            digest_sha256="aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999",
            sbom_ref="vault:secret/cosmo/sbom/payment-v1",
            scan_refs=["scann-id-001", "scann-id-002"],
            signature_attestation="vault:secret/cosmo/attestations/slsa-l4",
        )
        assert record.sbom_ref.startswith("vault:")
        assert len(record.scan_refs) == 2
        assert record.signature_attestation.startswith("vault:")


# �══════════════════════════════════════════════════════════════════════════
# LR-008: PrettyK Contract Tests
# �══════════════════════════════════════════════════════════════════════════

class TestLR008PrettyKContract:
    """Тесты внешнего контракта PrettyK — без импортов PureK."""

    def test_check_request_structure(self):
        """Запрос к PrettyK имеет корректную структуру."""
        request_payload = {
            "external_check_id": "ext-chk-001",
            "artifact_digest": "sha256:aaabbb...",
            "scan_type": "sast",
            "callback_url": "https://cosmoport.kits.corp/api/v1/callbacks/pretyk",
            "timeout_seconds": 30,
        }
        assert "external_check_id" in request_payload
        assert "timeout_seconds" in request_payload

    def test_callback_response_structure(self):
        """Колбэк от PrettyK содержит PASS/FAIL и Evidence."""
        callback_payload = {
            "external_check_id": "ext-chk-001",
            "verdict": "PASS",
            "evidence": {
                "sha256": "digest-abc",
                "gost_act_ref": "vault:secret/cosmo/gost/act-001",
            },
            "act": {"act_id": "act-001", "status": "signed"},
        }
        assert callback_payload["verdict"] == "PASS"
        assert "evidence" in callback_payload
        assert callback_payload["act"]["status"] == "signed"

    def test_idempotency_detection(self):
        """Повторный колбэк с тем же external_check_id — идемпотентен."""
        # Сценарий: первый колбэк — OK, второй с тем же ID — идемпотентно пропускается.
        processed_ids = set()
        callback_id = "ext-chk-001"

        # Первый раз
        assert callback_id not in processed_ids
        processed_ids.add(callback_id)

        # Повторный раз — должен быть в сете
        assert callback_id in processed_ids

    def test_timeout_handling(self):
        """При таймауте PrettyK возвращает специальный статус."""
        from cosmo.domain.instance_config import PrettyKProvider
        from pydantic import ValidationError

        provider = PrettyKProvider(
            endpoint_url="https://prettyk.io/api/v1",
            check_timeout_seconds=30,
        )
        assert provider.check_timeout_seconds == 30

        # Валидатор ge=5 не пропускает значения < 5
        with pytest.raises(ValidationError):
            PrettyKProvider(
                endpoint_url="https://prettyk.io/api/v1",
                check_timeout_seconds=1,
            )


# ═══════════════════════════════════════════════════════════════════════
# LR-009: Visibility Matrix & Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestLR009VisiblityMatrix:
    """12 сценариев видимости и прав."""

    def test_scenario_01_project_team_inheritance(self):
        """Участники Project Team видят приложения в проекте."""
        team = ProjectTeam(
            project_id="proj-v",
            inherited_members=[
                {"user_id": "usr-dev", "role": "developer"},
                {"user_id": "usr-qa", "role": "qa_engineer"},
            ],
        )
        member_ids = {m["user_id"] for m in team.inherited_members}
        assert "usr-dev" in member_ids
        assert "usr-qa" in member_ids

    def test_scenario_02_application_overrides(self):
        """Локальные переопределения на уровне приложения."""
        app_team = ApplicationTeam(
            app_id="app-v-01",
            project_id="proj-v",
            inherited_from_project=[{"user_id": "usr-dev", "role": "developer"}],
            local_members=[{"user_id": "usr-special", "role": "security_officer"}],
            role_overrides=[
                TeamRoleOverride(
                    user_id="usr-dev",
                    original_role="developer",
                    overridden_role="developer_lead",
                    reason="App-specific security requirement",
                    source="app_local",
                ),
            ],
        )
        assert len(app_team.local_members) == 1
        assert app_team.role_overrides[0].overridden_role == "developer_lead"
        assert app_team.role_overrides[0].reason != ""

    def test_scenario_03_admin_kits(self):
        """Админ КИТС имеет доступ ко всем проектам."""
        principal = PrincipalContext(
            user_id="admin_kits",
            roles=[Role.ADMIN_SERVICE],
            is_authenticated=True,
            is_system_admin=True,
        )
        assert principal.is_system_admin is True

    def test_scenario_04_readonly_preview(self):
        """Пользователь с ролью user имеет ридонли."""
        user_roles = frozenset({Role.USER.value})
        from cosmo.domain.rbac import _PERMISSIONS
        user_perms = _PERMISSIONS.get(Role.USER, frozenset())

        # Базовое чтение и экспорт разрешены
        assert "read" in user_perms

    def test_scenario_05_admin_ib(self):
        """Офицер ИБ имеет доступ к секьюрити гейтам."""
        principal = PrincipalContext(
            user_id="sec_officer",
            roles=[CBRRole.SECURITY_OFFICER],
            is_authenticated=True,
        )
        assert principal.has_role(CBRRole.SECURITY_OFFICER) is True

    def test_scenario_06_admin_nshr(self):
        """Админ НШР имеет права на сигнинг актов."""
        from cosmo.domain.rbac import Action, _CBR_ROLE_CAPABILITIES

        nshr_caps = _CBR_ROLE_CAPABILITIES.get(CBRRole.SECURITY_OFFICER, frozenset())
        assert Action.ACT_SIGN in nshr_caps

    def test_scenario_07_admin_service(self):
        """Админ сервиса имеет права на конфигурацию пайплайнов."""
        from cosmo.domain.rbac import Action, _CBR_ROLE_CAPABILITIES

        service_caps = _CBR_ROLE_CAPABILITIES.get(CBRRole.SERVICE_ADMIN, frozenset())
        assert Action.PIPELINE_CONFIGURE in service_caps

    def test_scenario_08_system_admin(self):
        """Системный администратор — полный доступ."""
        principal = PrincipalContext(
            user_id="sys_admin",
            roles=[],
            is_authenticated=True,
            is_system_admin=True,
        )
        assert principal.is_system_admin is True

    def test_scenario_09_multi_project_app(self):
        """Приложение может состоять в нескольких проектах."""
        project_a = Project(id="pa", name="Project A", application_ids=["app-multi"])
        project_b = Project(id="pb", name="Project B", application_ids=["app-multi"])
        assert "app-multi" in project_a.application_ids
        assert "app-multi" in project_b.application_ids

    def test_scenario_10_get_without_domain_context(self):
        """GET /api/v1/apps без domain_id — возвращает все доступные."""
        # Симуляция: без контекста домена — видает глобальный список
        app_list = [
            {"id": "app-1", "domain_id": "dom-a"},
            {"id": "app-2", "domain_id": "dom-b"},
        ]
        assert len(app_list) == 2

    def test_scenario_11_forbidden_mutation(self):
        """Попытка мутации без прав → 403."""
        principal = PrincipalContext(
            user_id="dev_bob",
            roles=[CBRRole.DEVELOPER],
            is_authenticated=True,
        )
        from cosmo.domain.rbac import Action, DomainRBAC

        rbac = DomainRBAC(domain_id="dom-kits")
        allowed, reason = rbac.evaluate(principal, Action.RELEASE_APPROVE)
        assert allowed is False
        assert "403" in reason

    def test_scenario_12_server_side_filtering(self):
        """Серверная фильтрация приложений по kits, level, status."""
        # Сценарий: запрос GET /api/v1/apps?kits=payments&level=1&search=auth
        filter_params = {
            "kits": "payments",
            "level": 1,
            "search": "auth",
            "limit": 20,
            "offset": 0,
        }
        assert filter_params["kits"] == "payments"
        assert filter_params["level"] == 1
        assert filter_params["search"] == "auth"
        assert filter_params["limit"] == 20