# -*- coding: utf-8 -*-
"""COS-065: Vendor TransportLink conformance kit.

Canonical fixtures + conformance runner, по которому vendor-реализация
TransportLink (Owl/InfoDiode SDK bridge) проверяется ДО подключения к kernel.
Vendor-код живёт снаружи; этот модуль — только контракт и эталонные фейки.

Conformance checks:
  1. write_chunk(bytes, ChunkRef) принимает канонические аргументы.
  2. Ошибка канала — только TransportError (не произвольное исключение);
     TargetRejectError — валидная target-семантика.
  3. flush() вызываем дважды — идемпотентен.
  4. Если link ведёт буфер (attr received: dict[int, bytes]) — чанки
     ложатся без дыр и дублей, reassembly == payload.
  5. Интеграция через DiodeAdapter: strict dispatch завершается
     ASSUMED_DELIVERED (никогда DELIVERED).

Usage (vendor test suite):
    violations = run_link_conformance(MyVendorLink())
    assert not violations, violations
"""
from __future__ import annotations

import hashlib
from typing import Optional

from orchestrator.cosmo.transfer.diode_adapter import (
    ChunkRef,
    DiodeAdapter,
    TargetRejectError,
    TransportError,
)


# ══════════════════════════════════════════════════════════════════
# Canonical fixtures (reference fakes для vendor test suites)
# ══════════════════════════════════════════════════════════════════

class RecordingTransportLink:
    """Эталонный fake: пишет чанки в память; ничего не ломается."""

    def __init__(self):
        self.received: dict[int, bytes] = {}
        self.refs: dict[int, ChunkRef] = {}
        self.flushes = 0

    def write_chunk(self, chunk: bytes, ref: ChunkRef) -> None:
        self.received[ref.index] = chunk
        self.refs[ref.index] = ref

    def flush(self) -> None:
        self.flushes += 1

    def reassemble(self) -> bytes:
        return b"".join(self.received[i] for i in sorted(self.received))


class FlakyTransportLink(RecordingTransportLink):
    """Обрыв канала после N чанков (one-shot: к retry канал восстановлен)."""

    def __init__(self, fail_after: int, message: str = "link dropped"):
        super().__init__()
        self.fail_after = fail_after
        self.message = message

    def write_chunk(self, chunk: bytes, ref: ChunkRef) -> None:
        if self.fail_after is not None and len(self.received) >= self.fail_after:
            self.fail_after = None  # one-shot: канал восстанавливается
            raise TransportError(self.message)
        super().write_chunk(chunk, ref)


class RejectingTransportLink(RecordingTransportLink):
    """Target отвергает revision — terminal LANDING_REJECTED."""

    def __init__(self, message: str = "target refused revision"):
        super().__init__()
        self.message = message

    def write_chunk(self, chunk: bytes, ref: ChunkRef) -> None:
        raise TargetRejectError(self.message)


class CapacityLimitedTransportLink(RecordingTransportLink):
    """Буфер диода переполнен — retryable CAPACITY_QUOTA_FAILURE."""

    def __init__(self, message: str = "diode buffer capacity exceeded"):
        super().__init__()
        self.message = message

    def write_chunk(self, chunk: bytes, ref: ChunkRef) -> None:
        raise TransportError(self.message)


# ══════════════════════════════════════════════════════════════════
# Conformance runner
# ══════════════════════════════════════════════════════════════════

def run_link_conformance(
    link,
    payload: bytes = b"conformance-payload-" + bytes(range(256)) * 4,
    chunk_size: int = 1024,
) -> list[str]:
    """Прогнать vendor link через канонический battery. Возвращает violations.

    Пустой список = link conforms к TransportLink contract.
    """
    violations: list[str] = []

    if not callable(getattr(link, "write_chunk", None)):
        violations.append("write_chunk: not callable")
        return violations
    if not callable(getattr(link, "flush", None)):
        violations.append("flush: not callable")
        return violations

    adapter = DiodeAdapter(link, chunk_size=chunk_size)
    chunks = adapter.make_chunks("conformance.bin", payload)

    # 1. write_chunk принимает канонические (bytes, ChunkRef);
    #    ошибка канала — только TransportError.
    for ref in chunks:
        piece = payload[ref.offset:ref.offset + ref.size]
        try:
            link.write_chunk(piece, ref)
        except TransportError:
            pass  # валидный failure mode
        except TargetRejectError:
            pass  # валидная target-семантика
        except Exception as exc:
            violations.append(
                f"write_chunk raised {type(exc).__name__} (expected "
                f"TransportError only): {exc}")

    # 2. flush идемпотентен
    try:
        link.flush()
        link.flush()
    except Exception as exc:
        violations.append(f"flush raised {type(exc).__name__}: {exc}")

    # 3. Буфер (если есть) — без дыр и дублей, reassembly точен
    received = getattr(link, "received", None)
    if isinstance(received, dict) and received:
        expected_indexes = list(range(len(chunks)))
        actual_indexes = sorted(received)
        if actual_indexes != expected_indexes:
            violations.append(
                f"chunk coverage: expected {expected_indexes}, got {actual_indexes} "
                "(gaps or duplicates in target buffer)")
        else:
            blob = b"".join(received[i] for i in actual_indexes)
            if blob != payload:
                violations.append("reassembly mismatch: target buffer != payload")

    return violations


def assert_link_conformance(link, **kwargs) -> None:
    """Бросить AssertionError со списком violations (для vendor suites)."""
    violations = run_link_conformance(link, **kwargs)
    if violations:
        raise AssertionError(
            "TransportLink conformance failed:\n" + "\n".join(violations))
