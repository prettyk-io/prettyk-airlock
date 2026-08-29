"""
COS-048: E2E Graph Topology — Domain → App → Group CRUD через Pydantic модели.

Проверяет: создание домена, приложений, групп, валидацию, сериализацию.
"""
import pytest
from cosmo.domain.domain_model import Domain, ForgeBinding, DomainQuota
from cosmo.domain.app_graph import (
    AppGraph, Application, Group, RepositoryBinding,
)


# ═══════════════════════════════════════════════════════════════════════
# Domain CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestDomainCRUD:
    def test_create_domain_minimal(self):
        d = Domain(
            id="d-graph-1", label="Payments",
            forge_binding=ForgeBinding(
                forge_type="gitea", url="http://gitea:3000",
                token_ref="VAULT/GITEA_TOKEN",
            ),
        )
        assert d.id == "d-graph-1"
        assert d.label == "Payments"
        assert d.quota.max_runs == 50

    def test_domain_with_custom_quota(self):
        d = Domain(
            id="d-custom", label="HighLoad",
            forge_binding=ForgeBinding(
                url="http://gitea:3000", token_ref="VAULT/GITEA_HL",
            ),
            quota=DomainQuota(max_runs=200, max_storage_gb=500, max_cpu=32),
        )
        assert d.quota.max_runs == 200
        assert d.quota.max_cpu == 32

    def test_domain_label_validation(self):
        with pytest.raises(Exception):
            Domain(
                id="d-bad", label="   ",
                forge_binding=ForgeBinding(
                    url="http://gitea:3000", token_ref="VAULT/T",
                ),
            )

    def test_domain_serialization(self):
        d = Domain(
            id="d-ser", label="Serial",
            forge_binding=ForgeBinding(
                forge_type="gitea", url="http://gitea:3000",
                token_ref="VAULT/GITEA_TOKEN",
            ),
            rbac_config={"roles": ["viewer", "developer", "operator", "admin", "owner"]},
        )
        data = d.model_dump()
        d2 = Domain.model_validate(data)
        assert d2.id == d.id
        assert d2.label == "Serial"
        assert d2.forge_binding.token_ref == "VAULT/GITEA_TOKEN"


# ═══════════════════════════════════════════════════════════════════════
# Application CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestApplicationCRUD:
    def test_create_app_level_1(self):
        app = Application(
            id="app-api", domain_id="d-graph-1", level=1,
            repo_binding=RepositoryBinding(
                forge_id="f1", repo_path="payments/api",
            ),
        )
        assert app.id == "app-api"
        assert app.level == 1
        assert app.repo_binding.repo_path == "payments/api"

    def test_create_app_level_0_library(self):
        app = Application(
            id="lib-utils", domain_id="d-graph-1", level=0,
            repo_binding=RepositoryBinding(
                forge_id="f1", repo_path="payments/utils",
            ),
        )
        assert app.level == 0

    def test_app_with_webhook(self):
        app = Application(
            id="app-hook", domain_id="d-graph-1", level=2,
            repo_binding=RepositoryBinding(
                forge_id="f1", repo_path="payments/web",
                webhook_id="hook-42",
            ),
        )
        assert app.repo_binding.webhook_id == "hook-42"

    def test_app_serialization_roundtrip(self):
        app = Application(
            id="app-rt", domain_id="d-graph-1", level=3,
            repo_binding=RepositoryBinding(
                forge_id="f2", repo_path="org/prod-app",
                default_branch="release",
            ),
            group_id="grp-backend",
            pipeline_plan_id="plan-app-rt",
        )
        data = app.model_dump()
        app2 = Application.model_validate(data)
        assert app2.id == app.id
        assert app2.repo_binding.repo_path == "org/prod-app"


# ═══════════════════════════════════════════════════════════════════════
# Group Hierarchy
# ═══════════════════════════════════════════════════════════════════════

class TestGroupHierarchy:
    def test_root_group(self):
        g = Group(id="grp-root", domain_id="d-graph-1", name="Backend")
        assert g.parent_group_id is None
        assert g.level == 0

    def test_child_group(self):
        g = Group(
            id="grp-child", domain_id="d-graph-1",
            parent_group_id="grp-root", level=1, name="Auth",
        )
        assert g.parent_group_id == "grp-root"
        assert g.level == 1

    def test_level_validation(self):
        with pytest.raises(Exception):
            Group(id="g", domain_id="d", level=5, name="Nope")

    def test_group_serialization(self):
        g = Group(
            id="grp-svc", domain_id="d-graph-1",
            parent_group_id="grp-root", level=2, name="Services",
        )
        data = g.model_dump()
        g2 = Group.model_validate(data)
        assert g2.name == "Services"


# ═══════════════════════════════════════════════════════════════════════
# AppGraph — full topology
# ═══════════════════════════════════════════════════════════════════════

class TestAppGraphTopology:
    def test_build_graph_from_domain(self):
        """Domain → AppGraph: apps, libraries, groups."""
        graph = AppGraph(
            domain="d-graph-1",
            groups=[
                Group(id="grp-api", domain_id="d-graph-1", name="API"),
                Group(id="grp-web", domain_id="d-graph-1", name="Web"),
            ],
            apps=[
                Application(
                    id="app-auth", domain_id="d-graph-1", level=1,
                    group_id="grp-api",
                    repo_binding=RepositoryBinding(forge_id="f1", repo_path="payments/auth"),
                ),
                Application(
                    id="app-gateway", domain_id="d-graph-1", level=1,
                    group_id="grp-api",
                    repo_binding=RepositoryBinding(forge_id="f1", repo_path="payments/gateway"),
                ),
            ],
            libraries=[
                Application(
                    id="lib-crypto", domain_id="d-graph-1", level=0,
                    repo_binding=RepositoryBinding(forge_id="f1", repo_path="shared/crypto"),
                ),
            ],
        )

        assert graph.domain == "d-graph-1"
        assert len(graph.groups) == 2
        assert len(graph.apps) == 2
        assert len(graph.libraries) == 1

        # Apps должны быть level 1-3
        for app in graph.apps:
            assert 1 <= app.level <= 3

        # Libraries должны быть level 0
        for lib in graph.libraries:
            assert lib.level == 0

    def test_no_cycles_in_groups(self):
        """AppGraph должен отбрасывать циклы в иерархии групп."""
        g1 = Group(id="g1", domain_id="d", parent_group_id="g2", name="G1")
        g2 = Group(id="g2", domain_id="d", parent_group_id="g1", name="G2")

        with pytest.raises(Exception):
            AppGraph(
                domain="d",
                groups=[g1, g2],
            )

    def test_graph_serialization(self):
        graph = AppGraph(
            domain="d-graph-1",
            groups=[Group(id="grp-x", domain_id="d-graph-1", name="X")],
            apps=[
                Application(
                    id="app-x", domain_id="d-graph-1", level=1,
                    group_id="grp-x",
                    repo_binding=RepositoryBinding(forge_id="f1", repo_path="x/y"),
                ),
            ],
        )
        data = graph.model_dump()
        g2 = AppGraph.model_validate(data)
        assert g2.domain == "d-graph-1"
        assert len(g2.apps) == 1


# ═══════════════════════════════════════════════════════════════════════
# RepositoryBinding variations
# ═══════════════════════════════════════════════════════════════════════

class TestRepositoryBindingVariations:
    def test_minimal_binding(self):
        rb = RepositoryBinding(forge_id="f1", repo_path="org/repo")
        assert rb.default_branch == "main"
        assert rb.webhook_id is None

    def test_custom_branch(self):
        rb = RepositoryBinding(forge_id="f1", repo_path="org/repo", default_branch="develop")
        assert rb.default_branch == "develop"

    def test_serialization(self):
        rb = RepositoryBinding(
            forge_id="f2", repo_path="org/web",
            default_branch="release", webhook_id="wh-99",
        )
        data = rb.model_dump()
        rb2 = RepositoryBinding.model_validate(data)
        assert rb2.repo_path == "org/web"
        assert rb2.webhook_id == "wh-99"