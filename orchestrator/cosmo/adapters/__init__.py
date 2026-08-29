"""Cosmoport 2.0 adapters — external tool integrations."""
from orchestrator.cosmo.adapters.execution_woodpecker import ExecutionAdapter, JobStatus, WoodpeckerAdapter
from orchestrator.cosmo.adapters.sonar_normalizer import (
    NormalizedFinding,
    build_sarif_210,
    extract_cwe,
    normalize_sonar_hotspots,
    normalize_sonar_issues,
)

__all__ = [
    # Woodpecker
    "ExecutionAdapter",
    "JobStatus",
    "WoodpeckerAdapter",
    # Sonar Normalrier
    "NormalizedFinding",
    "normalize_sonar_issues",
    "normalize_sonar_hotspots",
    "build_sarif_210",
    "extract_cwe",
]