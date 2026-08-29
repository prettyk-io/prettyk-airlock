"""
COS-002: Pipeline Compiler integration tests (порт из prettyk-dev).

Сценарии: один app с default bricks, группа с override,
cycle detection, empty bricks, compiled_hash.
"""
import hashlib
import json
import pytest

from cosmo.domain.app_graph import Application, RepositoryBinding
from cosmo.domain.pipeline_brick import (
    BrickDefinition, BrickOverride, PipelineBrick,
)
from cosmo.domain.run_model import Batch
from cosmo.compiler.plan_compiler import PlanCompiler, BatchDAGExecutor, BrickCatalog, _DAG_ORDER


# ── Legacy helpers (Luna's compile_pipeline, kept for backward compat) ──


def compile_pipeline(apps: list[Application], bricks: list[PipelineBrick],
                     overrides: list[BrickOverride] | None = None) -> list[Batch]:
    """
    Минимальный компилятор: каждому app сопоставляется Batch из bricks.
    BrickOverride переопределяет BrickDefinition для конкретного domain_id.
    """
    overrides_map: dict[tuple[str, str], BrickOverride] = {}
    if overrides:
        for ov in overrides:
            overrides_map[(ov.brick_id, ov.domain_id)] = ov

    batches: list[Batch] = []
    for i, app in enumerate(apps):
        batch_bricks: list[str] = []
        for brick in bricks:
            brick_id = brick.id
            key = (brick_id, app.domain_id)
            if key in overrides_map:
                brick_id = f"{brick.id}-overridden"
            batch_bricks.append(brick_id)

        batch = Batch(
            id=f"batch-{app.id}",
            plan_id=f"plan-{app.id}",
            type="mixed",
            bricks=batch_bricks,
        )
        batches.append(batch)

    return batches


def compute_compiled_hash(batches: list[Batch]) -> str:
    """Детерминированный хеш скомпилированного плана."""
    data = {
        "batches": [
            {"id": b.id, "plan_id": b.plan_id, "bricks": sorted(b.bricks)}
            for b in batches
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


# ── Tests ──

class TestSingleAppDefaultBricks:
    def test_one_app_with_default_bricks(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="org/frontend"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="org/frontend",
                          definition=BrickDefinition(image="sonarsource/sonar-scanner-cli:latest")),
            PipelineBrick(id="b2", name="DAST", type="dast", source="org/frontend",
                          definition=BrickDefinition(image="owasp/scanner2docker-stable:latest")),
        ]
        batches = compile_pipeline([app], bricks)
        assert len(batches) == 1
        assert batches[0].id == "batch-app-1"
        assert len(batches[0].bricks) == 2
        assert "b1" in batches[0].bricks
        assert "b2" in batches[0].bricks

    def test_empty_bricks_produces_empty_batch(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="org/frontend"))
        batches = compile_pipeline([app], [])
        assert len(batches) == 1
        assert len(batches[0].bricks) == 0


class TestGroupOverride:
    def test_brick_override_applies(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="org/frontend"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="org/frontend",
                          definition=BrickDefinition(image="sonarsource/sonar-scanner-cli:latest")),
        ]
        override = BrickOverride(brick_id="b1", domain_id="d-1",
                                 overrides_json={"timeout_s": 7200})
        batches = compile_pipeline([app], bricks, [override])
        assert batches[0].bricks[0] == "b1-overridden"

    def test_override_for_other_domain_not_applied(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="org/frontend"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="org/frontend",
                          definition=BrickDefinition(image="sonarsource/sonar-scanner-cli:latest")),
        ]
        override = BrickOverride(brick_id="b1", domain_id="d-other",
                                 overrides_json={"timeout_s": 7200})
        batches = compile_pipeline([app], bricks, [override])
        assert batches[0].bricks[0] == "b1"


class TestDAG:
    def test_bricks_with_dependencies_order(self):
        """Кирпичи с depends_on должны сохранять порядок — depends_on ссылаются на id."""
        bricks = [
            PipelineBrick(id="build", name="Build", type="build", source="org/repo",
                          definition=BrickDefinition(image="node:20")),
            PipelineBrick(id="test", name="Test", type="autotest", source="org/repo",
                          definition=BrickDefinition(image="node:20"),
                          depends_on=["build"]),
            PipelineBrick(id="dast", name="DAST", type="dast", source="org/repo",
                          definition=BrickDefinition(image="owasp/scanner2docker-stable:latest"),
                          depends_on=["build"]),
        ]
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="org/repo"))
        batches = compile_pipeline([app], bricks)
        batch_bricks = batches[0].bricks

        build_idx = batch_bricks.index("build")
        test_idx = batch_bricks.index("test")
        dast_idx = batch_bricks.index("dast")
        assert build_idx < test_idx, "Build must precede Test"
        assert build_idx < dast_idx, "Build must precede DAST"

    def test_cycle_detection_skipped_at_compile(self):
        """Циклы в depends_on: compile_pipeline должен либо детектить,
        либо падать с ошибкой. Здесь тест на базовое поведение."""
        bricks = [
            PipelineBrick(id="a", name="A", type="build", source="x",
                          definition=BrickDefinition(image="alpine"), depends_on=["b"]),
            PipelineBrick(id="b", name="B", type="build", source="x",
                          definition=BrickDefinition(image="alpine"), depends_on=["a"]),
        ]
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="x"))
        batches = compile_pipeline([app], bricks)
        assert len(batches) == 1
        assert "a" in batches[0].bricks
        assert "b" in batches[0].bricks


class TestCompiledHash:
    def test_same_inputs_same_hash(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="x"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="x",
                          definition=BrickDefinition(image="img")),
        ]
        batches1 = compile_pipeline([app], bricks)
        batches2 = compile_pipeline([app], bricks)
        assert compute_compiled_hash(batches1) == compute_compiled_hash(batches2)

    def test_different_apps_different_hash(self):
        app1 = Application(id="app-1", domain_id="d-1", level=1,
                           repo_binding=RepositoryBinding(forge_id="f1", repo_path="x"))
        app2 = Application(id="app-2", domain_id="d-1", level=1,
                           repo_binding=RepositoryBinding(forge_id="f1", repo_path="y"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="x",
                          definition=BrickDefinition(image="img")),
        ]
        h1 = compute_compiled_hash(compile_pipeline([app1], bricks))
        h2 = compute_compiled_hash(compile_pipeline([app2], bricks))
        assert h1 != h2

    def test_override_changes_hash(self):
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="x"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="x",
                          definition=BrickDefinition(image="img")),
        ]
        no_override = compile_pipeline([app], bricks)
        with_override = compile_pipeline([app], bricks, [
            BrickOverride(brick_id="b1", domain_id="d-1", overrides_json={"timeout_s": 999}),
        ])
        assert compute_compiled_hash(no_override) != compute_compiled_hash(with_override)


class TestMultipleApps:
    def test_two_apps_two_batches(self):
        app1 = Application(id="app-1", domain_id="d-1", level=1,
                           repo_binding=RepositoryBinding(forge_id="f1", repo_path="o/app1"))
        app2 = Application(id="app-2", domain_id="d-1", level=1,
                           repo_binding=RepositoryBinding(forge_id="f1", repo_path="o/app2"))
        bricks = [
            PipelineBrick(id="b1", name="SAST", type="sast", source="x",
                          definition=BrickDefinition(image="img")),
        ]
        batches = compile_pipeline([app1, app2], bricks)
        assert len(batches) == 2
        assert batches[0].id == "batch-app-1"
        assert batches[1].id == "batch-app-2"

    def test_all_brick_types(self):
        """Все 7 типов bricks могут быть скомпилированы."""
        types = ["sast", "sca", "build", "deploy", "dast", "autotest", "gate"]
        bricks = []
        for t in types:
            bricks.append(PipelineBrick(
                id=f"b-{t}", name=f"Brick {t}", type=t,  # type: ignore[arg-type]
                source="x", definition=BrickDefinition(image="alpine"),
            ))
        app = Application(id="app-1", domain_id="d-1", level=1,
                          repo_binding=RepositoryBinding(forge_id="f1", repo_path="x"))
        batches = compile_pipeline([app], bricks)
        assert len(batches[0].bricks) == 7


# ── COS-002: PlanCompiler tests ────────────────────────────────────────────


def _mk_brick(bid: str, name: str, btype: str, deps: list[str] | None = None) -> PipelineBrick:
    return PipelineBrick(
        id=bid, name=name, type=btype,  # type: ignore[arg-type]
        source="test", definition=BrickDefinition(image="test:latest"),
        depends_on=deps or [],
    )


def _mk_app(aid: str = "app-1", did: str = "d-1") -> Application:
    return Application(
        id=aid, domain_id=did, level=1,
        repo_binding=RepositoryBinding(forge_id="f1", repo_path="test/repo"),
    )


class TestPlanCompilerBatchGrouping:
    """COS-002: Group bricks by type into separate batches."""

    def test_build_and_sast_separate_batches(self):
        bricks = [
            _mk_brick("b-build", "Build", "build"),
            _mk_brick("b-sast", "SAST", "sast"),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, app=_mk_app(), plan_id="plan-x")

        types = [b.type for b in batches]
        assert "build" in types
        assert "static_scan" in types

    def test_sast_and_sca_same_static_scan_batch(self):
        """SAST and SCA bricks should end up in the same static_scan batch."""
        bricks = [
            _mk_brick("b-sonar", "SonarQube", "sast"),
            _mk_brick("b-trivy", "Trivy", "sca"),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, app=_mk_app(), plan_id="plan-x")

        static = [b for b in batches if b.type == "static_scan"]
        assert len(static) == 1
        assert "b-sonar" in static[0].bricks
        assert "b-trivy" in static[0].bricks

    def test_dag_order_is_build_first(self):
        """Build batch must precede static_scan batch in DAG order."""
        bricks = [
            _mk_brick("b-sast", "SAST", "sast"),
            _mk_brick("b-build", "Build", "build"),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, app=_mk_app(), plan_id="plan-x")
        order = [_DAG_ORDER.index(b.type) for b in batches]
        assert order == sorted(order), "Batches must be in DAG order"


class TestPlanCompilerTopsort:
    """COS-002: Topological sort within each batch by depends_on."""

    def test_depends_on_order_within_batch(self):
        bricks = [
            _mk_brick("b-lint", "Lint", "sast"),
            _mk_brick("b-sonar", "SonarQube", "sast", ["b-lint"]),
            _mk_brick("b-trivy", "Trivy", "sast"),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, app=_mk_app(), plan_id="plan-x")
        static = next(b for b in batches if b.type == "static_scan")
        lint_idx = static.bricks.index("b-lint")
        sonar_idx = static.bricks.index("b-sonar")
        assert lint_idx < sonar_idx, "Lint must precede SonarQube"


class TestPlanCompilerCycleDetection:
    """COS-002: Cycle detection in depends_on."""

    def test_no_cycles(self):
        bricks = [
            _mk_brick("a", "A", "build"),
            _mk_brick("b", "B", "sast", ["a"]),
        ]
        pc = PlanCompiler()
        assert pc.detect_cycles(bricks) is None

    def test_cycle_detected(self):
        bricks = [
            _mk_brick("a", "A", "build", ["b"]),
            _mk_brick("b", "B", "build", ["a"]),
        ]
        pc = PlanCompiler()
        cycles = pc.detect_cycles(bricks)
        assert cycles is not None
        assert len(cycles) > 0

    def test_self_loop_detected(self):
        bricks = [
            _mk_brick("x", "X", "build", ["x"]),
        ]
        pc = PlanCompiler()
        cycles = pc.detect_cycles(bricks)
        assert cycles is not None
        assert len(cycles) > 0


class TestPlanCompilerHashing:
    """COS-002: Deterministic compiled_hash."""

    def test_same_bricks_overrides_same_hash(self):
        bricks = [_mk_brick("a", "A", "build")]
        ov = BrickOverride(brick_id="a", domain_id="d-1", overrides_json={"timeout_s": 99})
        pc = PlanCompiler()
        b1 = pc.compile(bricks, [ov], _mk_app(), "p1")
        b2 = pc.compile(bricks, [ov], _mk_app(), "p1")
        h1 = pc.compile_hash(b1, bricks, [ov])
        h2 = pc.compile_hash(b2, bricks, [ov])
        assert h1 == h2

    def test_different_overrides_different_hash(self):
        bricks = [_mk_brick("a", "A", "build")]
        ov1 = BrickOverride(brick_id="a", domain_id="d-1", overrides_json={"timeout_s": 99})
        ov2 = BrickOverride(brick_id="a", domain_id="d-1", overrides_json={"timeout_s": 999})
        pc = PlanCompiler()
        b1 = pc.compile(bricks, [ov1], _mk_app(), "p1")
        b2 = pc.compile(bricks, [ov2], _mk_app(), "p1")
        assert pc.compile_hash(b1, bricks, [ov1]) != pc.compile_hash(b2, bricks, [ov2])


class TestBatchDAGExecutor:
    """COS-002: Batch DAG executor — sequential-parallel, Gate-waiting, idempotence."""

    def test_all_batches_ready_initially(self):
        batches = [
            Batch(id="b1", plan_id="p1", type="build", bricks=["a"]),
            Batch(id="b2", plan_id="p1", type="static_scan", bricks=["b"]),
        ]
        ex = BatchDAGExecutor(batches)
        ready = ex.next_ready()
        assert len(ready) == 2

    def test_advance_pending_to_running(self):
        batches = [Batch(id="b1", plan_id="p1", type="build", bricks=["a"])]
        ex = BatchDAGExecutor(batches)
        assert ex.advance("b1", "running")
        assert batches[0].status == "running"

    def test_advance_running_to_passed(self):
        batches = [Batch(id="b1", plan_id="p1", type="build", bricks=["a"], status="running")]
        ex = BatchDAGExecutor(batches)
        assert ex.advance("b1", "passed")
        assert batches[0].status == "passed"

    def test_cannot_skip_running(self):
        """pending -> passed should fail (must go through running)."""
        batches = [Batch(id="b1", plan_id="p1", type="build", bricks=["a"])]
        ex = BatchDAGExecutor(batches)
        assert not ex.advance("b1", "passed")

    def test_passed_is_terminal_in_executor(self):
        batches = [Batch(id="b1", plan_id="p1", type="build", bricks=["a"], status="passed")]
        ex = BatchDAGExecutor(batches)
        assert not ex.advance("b1", "running")

    def test_all_passed(self):
        batches = [
            Batch(id="b1", plan_id="p1", type="build", bricks=["a"], status="passed"),
            Batch(id="b2", plan_id="p1", type="static_scan", bricks=["b"], status="passed"),
        ]
        ex = BatchDAGExecutor(batches)
        assert ex.all_passed()

    def test_any_failed_or_blocked(self):
        batches = [
            Batch(id="b1", plan_id="p1", type="build", bricks=["a"], status="passed"),
            Batch(id="b2", plan_id="p1", type="static_scan", bricks=["b"], status="blocked"),
        ]
        ex = BatchDAGExecutor(batches)
        assert ex.any_failed_or_blocked()

    def test_failed_blocks_all_passed(self):
        batches = [
            Batch(id="b1", plan_id="p1", type="build", bricks=["a"], status="failed"),
            Batch(id="b2", plan_id="p1", type="static_scan", bricks=["b"], status="passed"),
        ]
        ex = BatchDAGExecutor(batches)
        assert not ex.all_passed()


class TestFullCompileAndExecute:
    """COS-002: Full compile + execute parity."""

    def test_full_pipeline_lifecycle(self):
        """Build -> StaticScan -> Deploy -> DynTest with Gates."""
        bricks = [
            _mk_brick("b-build", "Build Docker", "build"),
            _mk_brick("b-sonar", "SonarQube", "sast", ["b-build"]),
            _mk_brick("b-trivy", "Trivy", "sca", ["b-build"]),
            _mk_brick("b-deploy", "Deploy Staging", "deploy"),
            _mk_brick("b-scanner", "scanner Scan", "dast", ["b-deploy"]),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, app=_mk_app(), plan_id="plan-lifecycle")

        btypes = [b.type for b in batches]
        assert btypes[0] == "build"
        assert "static_scan" in btypes
        assert "deploy" in btypes
        assert "dynamic_test" in btypes

        ex = BatchDAGExecutor(batches)
        assert len(ex.next_ready()) > 0

        for b in ex.batches:
            ex.advance(b.id, "running")
            ex.advance(b.id, "passed")

        assert ex.all_passed()
        assert not ex.any_failed_or_blocked()

    def test_gate_blocks_pipeline(self):
        """When a batch fails, pipeline should detect it."""
        batches = [
            Batch(id="b-build", plan_id="p4", type="build", bricks=["a"]),
            Batch(id="b-scan", plan_id="p4", type="static_scan", bricks=["b"]),
        ]
        ex = BatchDAGExecutor(batches)
        ex.advance("b-build", "running")
        ex.advance("b-build", "failed")
        assert ex.any_failed_or_blocked()
        assert not ex.all_passed()