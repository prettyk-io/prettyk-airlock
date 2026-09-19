# -*- coding: utf-8 -*-
"""COS-151: canonical topological wipe for the isolated test PG.

Children (FK holders) are deleted strictly before their parents, so the
inter-test wipe never raises ForeignKeyViolation/IntegrityError. Covers EVERY
table with a FK onto runs / releases / apps / deployments — including the
scanner (scan_*), LR (application_*/release_batches/projects/kits_tags) and
deployment surfaces that were previously absent and left orphan rows.

Both test fixtures — ``cosmo/conftest.py`` (pg_client) and
``cosmo/integration/conftest.py`` (steel_thread) — bind to THIS module.
Do not fork the list; add new FK-bearing tables here.
"""
from __future__ import annotations

# The only circular FK in the schema is apps.pipeline_plan_id ↔
# pipeline_plans.app_id. Since pipeline_plans.app_id is NOT NULL, break it from
# the nullable side (apps). runs.batch_id is nullable; nullified defensively so
# the DELETE order stays robust to a future reorder.
CIRCULAR_NULLIFY = (
    "UPDATE apps SET pipeline_plan_id = NULL",
    "UPDATE runs SET batch_id = NULL",
)

# Child → parent. Rationale in comments per block.
DELETE_ORDER = (
    # COS-055 notifications (no FK to domain tables)
    "notification_inbox", "notification_events",
    "notification_subscriptions", "notification_channel_configs",
    # COS-081 gate decision trail (no FK — logical links only)
    "gate_decision_trail",
    # COS-077 transfer registry: items→plans, landing_states→items
    "transfer_received_revisions", "transfer_landing_states",
    "transfer_items", "transfer_plans",
    # COS-151 scanner: findings/evidence → scan_results;
    # scan_results → apps / cosmo_builds / releases / runs
    "scan_evidence", "scan_findings", "scan_results",
    # COS-151 deployments → apps / cosmo_builds / releases / domains
    "cosmo_deployments",
    # evidence_ledger → runs / batches
    "evidence_ledger",
    # pipeline chain: runs→batches, everything → pipeline_plans
    "plan_bricks", "runs", "batches", "gates", "releases",
    "pipeline_plans", "pipeline_bricks",
    # COS-083 builds → apps / domains
    "cosmo_builds",
    # COS-151 LR surfaces → apps / projects / kits_tags / release_types
    "application_kits_tags", "application_teams",
    "project_applications", "project_teams", "release_batches",
    "projects", "kits_tags", "release_types",
    # repo bindings → apps; then the domain parents
    "repo_bindings", "apps", "groups", "domains",
    # LR/artifact surfaces without FK (must not survive a run)
    "artifact_records", "instance_configuration",
    # COS-097/COS-108 ExecutionBase
    "cosmo_execution_handles", "cosmo_workspace_runs",
)