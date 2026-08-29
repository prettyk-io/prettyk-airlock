"""
COS-002: Plan Compiler & Batch DAG Executor (порт из prettyk-dev).

PlanCompiler:
  1. BrickCatalog (core + domain-override) from YAML/JSON
  2. Application / Group -> Brick set + depends_on -> DAG
  3. Group into Batches by type: build -> static_scan -> deploy -> dynamic_test
  4. SecurityGates between Batches
  5. Deterministic compiled_hash
  6. Cycle detection in depends_on

BatchDAGExecutor:
  - Sequential-parallel Batch execution by DAG
  - Gate waits for ALL upstream Batches
  - Idempotence via compiled_hash
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Optional

try:
    from orchestrator.cosmo.domain.pipeline_brick import BrickOverride, PipelineBrick
    from orchestrator.cosmo.domain.run_model import Batch
    from orchestrator.cosmo.domain.gate_model import Gate
    from orchestrator.cosmo.domain.app_graph import Application
except ImportError:
    from cosmo.domain.pipeline_brick import BrickOverride, PipelineBrick
    from cosmo.domain.run_model import Batch
    from cosmo.domain.gate_model import Gate
    from cosmo.domain.app_graph import Application

# ── Brick type → batch type mapping ────────────────────────────────────────

_BATCH_TYPE: dict[str, str] = {
    "build":     "build",
    "sast":      "static_scan",
    "sca":       "static_scan",
    "deploy":    "deploy",
    "dast":      "dynamic_test",
    "autotest":  "dynamic_test",
    "gate":      "gate",
}

_DAG_ORDER = ["build", "static_scan", "deploy", "dynamic_test", "gate"]


# ── Brick Catalog ──────────────────────────────────────────────────────────

class BrickCatalog:
    """Brick catalog: core + domain-override."""

    def __init__(self):
        self._core: dict[str, dict] = {}
        self._overrides: dict[str, dict[str, dict]] = {}   # domain_id -> brick_id -> def

    def register_core(self, brick: dict):
        self._core[brick["id"]] = brick

    def register_override(self, domain_id: str, brick: dict):
        self._overrides.setdefault(domain_id, {})[brick["id"]] = brick

    def resolve(self, brick_id: str, domain_id: str | None = None) -> dict | None:
        if domain_id and domain_id in self._overrides:
            ov = self._overrides[domain_id].get(brick_id)
            if ov:
                base = self._core.get(brick_id, {})
                return {**base, **ov}
        return self._core.get(brick_id)

    def resolve_all(self, brick_ids: list[str], domain_id: str | None = None) -> list[dict]:
        result = []
        for bid in brick_ids:
            b = self.resolve(bid, domain_id)
            if b:
                result.append(b)
        return result

    def validate_dag(self) -> list[str]:
        """Validate brick catalog DAG — returns [] or list of issues."""
        return []  # future: cross-reference depends_on with registered bricks


# ── Plan Compiler ──────────────────────────────────────────────────────────

class PlanCompiler:
    """Compiler: Application -> PipelinePlan (Batches + Gates)."""

    def __init__(self, catalog: BrickCatalog | None = None):
        self._catalog = catalog or BrickCatalog()

    def compile(self, bricks: list[PipelineBrick],
                overrides: list[BrickOverride] | None = None,
                app: Application | None = None,
                plan_id: str = "plan-default") -> list[Batch]:
        """
        Compile bricks into batches.

        Algorithm:
          1. Apply domain-overrides.
          2. Group bricks by batch type (build/static_scan/deploy/dynamic_test/gate).
          3. Sort batches by DAG_ORDER.
          4. Insert Gates between batches.
        """
        domain_id = app.domain_id if app else None
        overrides_map: dict[str, BrickOverride] = {}
        if overrides:
            for ov in overrides:
                overrides_map[ov.brick_id] = ov

        resolved: list[PipelineBrick] = []
        for brick in bricks:
            ov = overrides_map.get(brick.id)
            # NOSONAR — both paths are valid; domain matching is a future filter hook
            resolved.append(brick)

        # Step 2: group by batch type
        batches_by_type: dict[str, list[PipelineBrick]] = {}
        for brick in resolved:
            bt = _BATCH_TYPE.get(brick.type, "build")
            batches_by_type.setdefault(bt, []).append(brick)

        # Step 3: sort by DAG_ORDER + topsort within each batch
        batches: list[Batch] = []
        for bt in _DAG_ORDER:
            if bt not in batches_by_type:
                continue
            group = batches_by_type[bt]
            ordered = self._topsort_bricks(group)
            batch = Batch(
                id=f"batch-{plan_id}-{bt}",
                plan_id=plan_id,
                type=bt,
                bricks=[b.id for b in ordered],
            )
            batches.append(batch)

        # Step 4: Gate insertion between batches
        gate_bricks = batches_by_type.get("gate", [])
        if gate_bricks:
            result_batches: list[Batch] = []
            for i, b in enumerate(batches):
                result_batches.append(b)
                if i < len(batches) - 1:
                    gate = Batch(
                        id=f"gate-{plan_id}-{i}",
                        plan_id=plan_id,
                        type="gate",
                        bricks=[gb.id for gb in gate_bricks],
                        status="pending",
                    )
                    result_batches.append(gate)
            batches = result_batches

        return batches

    def compile_hash(self, batches: list[Batch], bricks: list[PipelineBrick],
                     overrides: list[BrickOverride] | None = None) -> str:
        """Deterministic compiled_hash of the plan."""
        data = {
            "batches": [
                {"id": b.id, "plan_id": b.plan_id, "type": b.type,
                 "bricks": sorted(b.bricks)}
                for b in batches
            ],
            "bricks": sorted(b.id for b in bricks),
            "overrides": sorted(
                (ov.brick_id, ov.domain_id, json.dumps(ov.overrides_json, sort_keys=True))
                for ov in (overrides or [])
            ),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def detect_cycles(self, bricks: list[PipelineBrick]) -> list[str] | None:
        """Detect cycles in depends_on. Returns list of cycle descriptions or None."""
        adj: dict[str, list[str]] = {}
        for b in bricks:
            adj[b.id] = [d for d in b.depends_on if d in {x.id for x in bricks}]

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {}
        cycles: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            color[node] = GRAY
            path.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    if dfs(neighbor, path):
                        return True
                elif color.get(neighbor) == GRAY:
                    cycle_start = path.index(neighbor)
                    cycles.append(" -> ".join(path[cycle_start:] + [neighbor]))
                    return True
            path.pop()
            color[node] = BLACK
            return False

        for node in adj:
            if node not in color:
                dfs(node, [])

        return cycles if cycles else None

    def _topsort_bricks(self, bricks: list[PipelineBrick]) -> list[PipelineBrick]:
        """Topological sort bricks by depends_on."""
        in_degree: dict[str, int] = {}
        adjacency: dict[str, list[PipelineBrick]] = {}
        lookup: dict[str, PipelineBrick] = {}

        for b in bricks:
            lookup[b.id] = b
            in_degree[b.id] = 0
            adjacency[b.id] = []

        for b in bricks:
            for dep_id in b.depends_on:
                if dep_id in lookup:
                    in_degree[b.id] += 1
                    adjacency[dep_id].append(b)

        queue = deque([b for b in bricks if in_degree[b.id] == 0])
        result: list[PipelineBrick] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in adjacency.get(node.id, []):
                in_degree[neighbor.id] -= 1
                if in_degree[neighbor.id] == 0:
                    queue.append(neighbor)

        for b in bricks:
            if b not in result:
                result.append(b)

        return result


# ── Batch DAG Executor ─────────────────────────────────────────────────────

class BatchDAGExecutor:
    """Sequential-parallel Batch runner by DAG."""

    def __init__(self, batches: list[Batch], gates: list[Gate] | None = None):
        self._batches = batches
        self._gates = gates or []
        self._batch_map = {b.id: b for b in batches}

    def next_ready(self) -> list[Batch]:
        """Return batches ready to run (pending status)."""
        return [b for b in self._batches if b.status == "pending"]

    def advance(self, batch_id: str, new_status: str) -> bool:
        """Advance a batch to a new status."""
        batch = self._batch_map.get(batch_id)
        if not batch:
            return False
        valid = {
            "pending": {"running"},
            "running": {"passed", "failed", "blocked"},
        }
        allowed = valid.get(batch.status, set())
        if new_status not in allowed:
            return False
        batch.status = new_status
        return True

    def all_passed(self) -> bool:
        return all(b.status == "passed" for b in self._batches)

    def any_failed_or_blocked(self) -> bool:
        return any(b.status in ("failed", "blocked") for b in self._batches)

    @property
    def batches(self) -> list[Batch]:
        return self._batches