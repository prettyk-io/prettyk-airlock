# -*- coding: utf-8 -*-
"""SAST-STEP-1: канонический маркер отчёта source-SAST в логах CI-шага.

CI-шаг (Woodpecker) не имеет прямого доступа к Cosmo-поверхностям; канал
передачи отчёта — тот же, что у docker_build-digest (COS-164): канонический
маркер в логах шага, который Cosmo снимает durable-захватом
(``control_plane.sast_capture`` → ArtifactStore + EvidenceLedgerEntry).

Формат маркера — одна строка в stderr/stdout шага «sonar-report»:

    [prettyk-sast-report] format=<sarif|ce-issues> sha256=<64hex> bytes=<n> b64=<base64(gzip(report))>

Честность:
  - маркер отсутствует (шаг упал/не дошёл) → захват поднимает
    ``MissingSastReportError`` + alert-след; отчёт не выдумывается;
  - sha256/bytes не сходятся с payload → ``InvalidSastReportError``.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import re
from dataclasses import dataclass
from typing import Optional

SAST_REPORT_MARKER_PREFIX = "[prettyk-sast-report]"
KNOWN_SAST_REPORT_FORMATS = ("sarif", "ce-issues")

_MARKER_RE = re.compile(
    r"\[prettyk-sast-report\]\s+format=(?P<format>[a-z0-9-]+)\s+"
    r"sha256=(?P<sha256>[0-9a-f]{64})\s+bytes=(?P<bytes>\d+)\s+"
    r"b64=(?P<b64>[A-Za-z0-9+/=]+)"
)


@dataclass(frozen=True)
class SastReportMarker:
    """Разобранный маркер отчёта: метаданные + распакованный payload."""

    format: str
    sha256: str
    bytes_len: int
    payload: bytes


def emit_sast_report_marker(report: bytes, *, fmt: str = "sarif") -> str:
    """Собрать канонический маркер для печати в лог шага (одна строка)."""
    if fmt not in KNOWN_SAST_REPORT_FORMATS:
        raise ValueError(
            f"unknown report format {fmt!r}; expected {KNOWN_SAST_REPORT_FORMATS}"
        )
    compressed = gzip.compress(report)
    digest = hashlib.sha256(report).hexdigest()
    return (
        f"{SAST_REPORT_MARKER_PREFIX} format={fmt} sha256={digest} "
        f"bytes={len(report)} b64={base64.b64encode(compressed).decode('ascii')}"
    )


def parse_sast_report_marker(line: str) -> Optional[SastReportMarker]:
    """Разобрать маркер из одной строки лога; None — не маркер или битый payload."""
    match = _MARKER_RE.search(line or "")
    if match is None:
        return None
    try:
        compressed = base64.b64decode(match.group("b64"), validate=True)
        payload = gzip.decompress(compressed)
    except Exception:  # noqa: BLE001 — битый payload → маркер невалиден
        return None
    return SastReportMarker(
        format=match.group("format"),
        sha256=match.group("sha256"),
        bytes_len=int(match.group("bytes")),
        payload=payload,
    )


def find_sast_report_marker(logs: dict[str, list[str]]) -> Optional[SastReportMarker]:
    """Последний валидный маркер в порядке ПАЙПЛАЙНА (dict insertion order).

    ``collect_all_logs`` кладёт шаги в порядке pipeline-дерева; report-шаг идёт
    после scan-шага, поэтому его маркер — последний. Не сортируем по имени:
    алфавит не отражает порядок шагов.
    """
    found: Optional[SastReportMarker] = None
    for lines in logs.values():
        for line in lines or []:
            marker = parse_sast_report_marker(line)
            if marker is not None:
                found = marker
    return found


def verify_sast_report_marker(marker: SastReportMarker) -> str:
    """Пустая строка — маркер консистентен; иначе — причина несоответствия."""
    if marker.format not in KNOWN_SAST_REPORT_FORMATS:
        return f"unknown format {marker.format!r}"
    if len(marker.payload) != marker.bytes_len:
        return (
            f"bytes mismatch: marker says {marker.bytes_len}, "
            f"payload has {len(marker.payload)}"
        )
    digest = hashlib.sha256(marker.payload).hexdigest()
    if digest != marker.sha256:
        return f"sha256 mismatch: marker says {marker.sha256}, payload has {digest}"
    return ""


__all__ = [
    "KNOWN_SAST_REPORT_FORMATS",
    "SAST_REPORT_MARKER_PREFIX",
    "SastReportMarker",
    "emit_sast_report_marker",
    "find_sast_report_marker",
    "parse_sast_report_marker",
    "verify_sast_report_marker",
]
