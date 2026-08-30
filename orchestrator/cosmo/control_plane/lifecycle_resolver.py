# -*- coding: utf-8 -*-
"""SAN-014: 8-Step Clean Lifecycle Resolver & Batch Generator."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class LCStepConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_id: str = Field(..., min_length=1)
    step_name: str = Field(..., min_length=1)
    section: str = Field(default="static")
    step_order: int = Field(ge=0, le=7, default=0)
    step_required: bool = Field(default=True)
    step_enabled: bool = Field(default=True)
    step_on_failure: str = Field(default="fail")

CANONICAL_8_STEPS = {
    "build": LCStepConfig(step_id="build", step_name="Build", section="build", step_order=0, step_required=True),
    "unit_tests": LCStepConfig(step_id="unit_tests", step_name="Unit Tests", section="build", step_order=1, step_required=True),
    "docs_gen": LCStepConfig(step_id="docs_gen", step_name="Docs Gen", section="build", step_order=2, step_required=False, step_on_failure="warn"),
    "sonarqube": LCStepConfig(step_id="sonarqube", step_name="SonarQube", section="static_scan", step_order=3, step_required=True),
    "trivy": LCStepConfig(step_id="trivy", step_name="Trivy", section="static_scan", step_order=4, step_required=True),
    "codescoring": LCStepConfig(step_id="codescoring", step_name="CodeScoring", section="static_scan", step_order=5, step_required=False, step_on_failure="warn"),
    "kcs": LCStepConfig(step_id="kcs", step_name="Kaspersky", section="static_scan", step_order=6, step_required=False, step_on_failure="warn"),
    "deploy": LCStepConfig(step_id="deploy", step_name="Deploy", section="deploy", step_order=7, step_required=True),
}

class BuildBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    steps: list[dict] = Field(default_factory=list)
    name: str = "Build"

class StaticScanBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    steps: list[dict] = Field(default_factory=list)
    name: str = "StaticScan"

class DeployBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    steps: list[dict] = Field(default_factory=list)
    name: str = "Deploy"

class LifecycleResolver:
    def __init__(self, domain_defaults=None, app_overrides=None):
        self._domain = domain_defaults or {}
        self._app = app_overrides or {}

    def resolve(self):
        result = {}
        for step_id, canonical in CANONICAL_8_STEPS.items():
            data = canonical.model_dump()
            if step_id in self._domain:
                data.update(self._domain[step_id])
            if step_id in self._app:
                app_data = dict(self._app[step_id])
                if data.get("step_required") and not app_data.get("step_required", True):
                    app_data["step_required"] = True
                data.update(app_data)
            # SAN-014: required steps cannot be disabled
            if data.get("step_required"):
                data["step_enabled"] = True
            result[step_id] = LCStepConfig(**data)
        return result

    def resolve_as_list(self):
        return sorted(self.resolve().values(), key=lambda s: s.step_order)

    def generate_batches(self):
        steps = self.resolve_as_list()
        build = [s.model_dump() for s in steps if s.section == "build" and s.step_enabled]
        static = [s.model_dump() for s in steps if s.section == "static_scan" and s.step_enabled]
        deploy = [s.model_dump() for s in steps if s.section == "deploy" and s.step_enabled]
        return {
            "build": BuildBatch(steps=build).model_dump(),
            "static_scan": StaticScanBatch(steps=static).model_dump(),
            "deploy": DeployBatch(steps=deploy).model_dump(),
        }

    def validate_required_coverage(self):
        steps = self.resolve_as_list()
        required = [s for s in steps if s.step_required]
        disabled = [s for s in required if not s.step_enabled]
        return {"total_required": len(required), "disabled": len(disabled), "disabled_ids": [s.step_id for s in disabled], "ok": len(disabled) == 0}
