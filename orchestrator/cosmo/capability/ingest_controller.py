"""
COS-074: Ingest Token Bucket — rate-limited SARIF feed controller для SonarQube Community.

Контроллер читает SARIF-отчёты из очереди Valkey Stream `sonar.ingest`
и медленно скармливает их в центральный Standalone SonarQube.

Стратегия:
  - max_concurrency=2: не больше двух одновременных задач
  - rate_limit_delay_s=1.0: пауза между задачами
  - check_sonar_health(): если PENDING+IN_PROGRESS >3 — backoff
  - XACK только после успешного принятия задачи SonarQube
  - Exponential backoff на 504 / DB lock contention

Инварианты:
  - Valkey — только транспорт. При сбросе → восстановление из PG.
  - 50 отчётов → равномерное скармливание батчами по 2
  - Падение SonarQube → задачи не теряются, QUEUED_FOR_INGEST
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("cosmoport.ingest_controller")


# ── Ingest States ────────────────────────────────────────────────────────────

class IngestState(str, Enum):
    QUEUED = "queued"                    # в очереди Valkey, ждёт обработки
    PENDING_CE = "pending_ce"            # отправлен в SonarQube CE
    IN_PROGRESS = "in_progress"          # обрабатывается SonarQube Compute Engine
    PROCESSED = "processed"              # успешно обработан
    REJECTED = "rejected"                # отклонён SonarQube (валидация)
    ERROR = "error"                      # ошибка при отправке
    TIMED_OUT = "timed_out"              # превышен таймаут обработки


# ── Ingest Event ─────────────────────────────────────────────────────────────

@dataclass
class IngestEvent:
    """Событие отчёта для загрузки в SonarQube."""
    event_id: str                        # Valkey Stream message ID
    s3_uri: str                          # путь к SARIF-отчёту (S3 / MinIO / local)
    project_key: str                     # SonarQube project key
    run_id: str                          # ID прогона-источника
    batch_id: str = ""                   # ID batch'а
    state: IngestState = IngestState.QUEUED
    attempt: int = 0                     # количество попыток отправки
    last_error: str = ""                 # последняя ошибка
    xacked: bool = False                 # подтверждён ли XACK
    created_at: float = field(default_factory=time.time)

    def event_key(self) -> str:
        return f"{self.project_key}:{self.s3_uri.split('/')[-1]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "s3_uri": self.s3_uri,
            "project_key": self.project_key,
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "state": self.state.value,
            "attempt": self.attempt,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }


# ── Abstract Backends ────────────────────────────────────────────────────────

class ValkeyStreamBackend(ABC):
    """Абстракция над Valkey Stream для тестируемости."""

    @abstractmethod
    def xreadgroup(self, group: str, consumer: str, stream: str, count: int,
                   block_ms: int = 0) -> List[Tuple[str, Dict[str, Any]]]:
        """Читать сообщения из потока через Consumer Group."""
        raise NotImplementedError

    @abstractmethod
    def xack(self, stream: str, group: str, message_id: str) -> bool:
        """Подтвердить обработку сообщения."""
        raise NotImplementedError

    @abstractmethod
    def xadd(self, stream: str, data: Dict[str, str]) -> str:
        """Добавить сообщение в поток. Возвращает message_id."""
        raise NotImplementedError

    @abstractmethod
    def xpending(self, stream: str, group: str) -> int:
        """Количество pending (неподтверждённых) сообщений."""
        raise NotImplementedError

    @abstractmethod
    def stream_length(self, stream: str) -> int:
        """Длина потока."""
        raise NotImplementedError


class SonarQubeBackend(ABC):
    """Абстракция над SonarQube Compute Engine API."""

    @abstractmethod
    def get_ce_activity(self, status_filter: str = "PENDING,IN_PROGRESS") -> List[Dict[str, Any]]:
        """GET /api/ce/activity?status=PENDING,IN_PROGRESS."""
        raise NotImplementedError

    @abstractmethod
    def submit_report(self, project_key: str, s3_uri: str) -> Tuple[bool, str]:
        """Отправить SARIF-отчёт в SonarQube. Возвращает (успех, task_id или ошибка)."""
        raise NotImplementedError

    @abstractmethod
    def get_task_status(self, task_id: str) -> Dict[str, Any] | None:
        """GET /api/ce/task?id=task_id."""
        raise NotImplementedError


# ── In-Memory Mock Backends ─────────────────────────────────────────────────

class MockValkeyStreamBackend(ValkeyStreamBackend):
    """In-memory Valkey Stream для тестов."""

    def __init__(self):
        self._streams: Dict[str, list[Tuple[str, Dict[str, Any]]]] = {}
        self._groups: Dict[str, Dict[str, set[str]]] = {}  # stream → group → {message_ids}
        self._xacked: Dict[str, Dict[str, set[str]]] = {}   # stream → group → {acked_ids}
        self._counter = 0

    def xadd(self, stream: str, data: Dict[str, str]) -> str:
        self._counter += 1
        msg_id = f"msg-{self._counter}-{uuid.uuid4().hex[:8]}"
        self._streams.setdefault(stream, []).append((msg_id, dict(data)))
        return msg_id

    def xreadgroup(self, group: str, consumer: str, stream: str, count: int,
                   block_ms: int = 0) -> List[Tuple[str, Dict[str, Any]]]:
        self._groups.setdefault(stream, {}).setdefault(group, set())
        acked = self._xacked.get(stream, {}).get(group, set())
        all_msgs = self._streams.get(stream, [])

        result: List[Tuple[str, Dict[str, Any]]] = []
        for msg_id, data in all_msgs:
            if msg_id in acked:
                continue
            if msg_id in self._groups[stream][group]:
                continue  # уже в обработке
            self._groups[stream][group].add(msg_id)
            result.append((msg_id, data))
            if len(result) >= count:
                break
        return result

    def xack(self, stream: str, group: str, message_id: str) -> bool:
        self._xacked.setdefault(stream, {}).setdefault(group, set())
        self._xacked[stream][group].add(message_id)
        # Удалить из pending
        if stream in self._groups and group in self._groups[stream]:
            self._groups[stream][group].discard(message_id)
        return True

    def xpending(self, stream: str, group: str) -> int:
        acked = self._xacked.get(stream, {}).get(group, set())
        in_group = self._groups.get(stream, {}).get(group, set())
        return len(in_group - acked)

    def stream_length(self, stream: str) -> int:
        return len(self._streams.get(stream, []))


class MockSonarQubeBackend(SonarQubeBackend):
    """In-memory SonarQube CE для тестов."""

    def __init__(self, max_concurrent: int = 3, sim_overload: bool = False,
                 sim_unavailable: bool = False, sim_timeout: bool = False):
        self.max_concurrent = max_concurrent
        self.sim_overload = sim_overload      # больше max_concurrent задач
        self.sim_unavailable = sim_unavailable  # SonarQube упал
        self.sim_timeout = sim_timeout          # 504 Gateway Timeout
        self._task_counter = 0
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._submitted: List[Tuple[str, str]] = []  # (project_key, s3_uri) history

    def get_ce_activity(self, status_filter: str = "PENDING,IN_PROGRESS") -> List[Dict[str, Any]]:
        if self.sim_unavailable:
            raise ConnectionError("SonarQube unavailable")
        if self.sim_overload:
            return [
                {"taskId": "task-1", "status": "PENDING"},
                {"taskId": "task-2", "status": "IN_PROGRESS"},
                {"taskId": "task-3", "status": "PENDING"},
                {"taskId": "task-4", "status": "IN_PROGRESS"},
                {"taskId": "task-5", "status": "PENDING"},
            ]
        return [
            {"taskId": "task-1", "status": "IN_PROGRESS"},
        ]

    def submit_report(self, project_key: str, s3_uri: str) -> Tuple[bool, str]:
        if self.sim_unavailable:
            return False, "Connection refused"
        if self.sim_timeout:
            return False, "504 Gateway Timeout"
        self._task_counter += 1
        task_id = f"ce-task-{self._task_counter}"
        self._tasks[task_id] = {"project_key": project_key, "status": "PENDING"}
        self._submitted.append((project_key, s3_uri))
        return True, task_id

    def get_task_status(self, task_id: str) -> Dict[str, Any] | None:
        return self._tasks.get(task_id)

    @property
    def submitted_count(self) -> int:
        return len(self._submitted)


# ── Ingest Token Bucket ─────────────────────────────────────────────────────

class IngestTokenBucket:
    """COS-074: rate-limited контроллер для SARIF-отчётов в SonarQube CE.

    State machine: QUEUED → PENDING_CE → IN_PROGRESS → PROCESSED/REJECTED/ERROR.
    """

    _STREAM = "sonar.ingest"
    _GROUP = "cosmo-ingest"
    _MAX_RETRIES = 5
    _BACKOFF_BASE = 2.0          # exponential backoff base (сек)
    _SQ_OVERLOAD_THRESHOLD = 3    # если >3 задач PENDING/IN_PROGRESS → пауза

    def __init__(
        self,
        valkey: ValkeyStreamBackend,
        sonar: SonarQubeBackend,
        max_concurrency: int = 2,
        rate_limit_delay_s: float = 1.0,
        consumer_id: str = "",
    ):
        self._valkey = valkey
        self._sonar = sonar
        self._max_concurrency = max_concurrency
        self._rate_limit_delay_s = rate_limit_delay_s
        self._consumer_id = consumer_id or f"consumer-{uuid.uuid4().hex[:8]}"

        self._lock = threading.Lock()
        self._events: Dict[str, IngestEvent] = {}  # event_id → state
        self._last_poll_ts: float = 0.0
        self._paused_until: float = 0.0             # backoff-пауза
        self._stats = {"polled": 0, "submitted": 0, "xacked": 0, "errors": 0,
                        "backoffs": 0, "skips": 0}

    # ── Queue Operations ─────────────────────────────────────────────────────

    def poll_queue(self, count: int | None = None) -> List[IngestEvent]:
        """Читать до max_concurrency сообщений из Valkey Stream.

        Rate-limited: не чаще rate_limit_delay_s.
        Backoff: если _paused_until в будущем — пропуск.
        """
        now = time.time()

        # Rate limit guard
        if now - self._last_poll_ts < self._rate_limit_delay_s:
            self._stats["skips"] += 1
            return []

        # Backoff guard
        if now < self._paused_until:
            self._stats["skips"] += 1
            return []

        self._last_poll_ts = now

        batch_size = count or self._max_concurrency
        raw = self._valkey.xreadgroup(
            self._GROUP, self._consumer_id, self._STREAM,
            count=batch_size, block_ms=100,
        )

        events: List[IngestEvent] = []
        for msg_id, data in raw:
            event = IngestEvent(
                event_id=msg_id,
                s3_uri=data.get("s3_uri", data.get("report_path", "")),
                project_key=data.get("project_key", data.get("projectKey", "")),
                run_id=data.get("run_id", ""),
                batch_id=data.get("batch_id", ""),
            )
            self._events[msg_id] = event
            events.append(event)
            self._stats["polled"] += 1

        return events

    # ── SonarQube Health ─────────────────────────────────────────────────────

    def check_sonar_health(self) -> Tuple[bool, int]:
        """Опрос SonarQube CE на предмет загрузки.

        Returns:
            (healthy, pending_count).
            healthy=False → пауза с exponential backoff.
        """
        try:
            tasks = self._sonar.get_ce_activity("PENDING,IN_PROGRESS")
            pending = len(tasks)

            if pending > self._SQ_OVERLOAD_THRESHOLD:
                self._apply_backoff()
                return False, pending

            return True, pending

        except Exception as exc:
            logger.warning("SonarQube health check failed: %s", exc)
            self._apply_backoff()
            return False, 0

    def _apply_backoff(self) -> None:
        """Экспоненциальный backoff: 2s → 4s → 8s → 16s → cap 60s."""
        backoff = min(
            self._BACKOFF_BASE * (2 ** self._stats["backoffs"]),
            60.0,
        )
        self._paused_until = time.time() + backoff
        self._stats["backoffs"] += 1
        logger.info("Backoff applied: %.1fs (backoff #%d)", backoff, self._stats["backoffs"])

    # ── Feed ─────────────────────────────────────────────────────────────────

    def feed_events(self, events: List[IngestEvent]) -> int:
        """Скормить события SonarQube. Возвращает количество успешно отправленных.

        XACK подтверждается только после успешного принятия задачи SonarQube.
        При 504/ошибке — exponential retry (до 5 попыток).
        """
        submitted = 0

        for event in events:
            if event.state != IngestState.QUEUED:
                continue

            # Проверить попытки
            if event.attempt >= self._MAX_RETRIES:
                event.state = IngestState.REJECTED
                event.last_error = f"Max retries ({self._MAX_RETRIES}) exceeded"
                continue

            event.attempt += 1

            success, task_id = self._sonar.submit_report(
                event.project_key, event.s3_uri,
            )

            if success:
                event.state = IngestState.PENDING_CE
                self._valkey.xack(self._STREAM, self._GROUP, event.event_id)
                event.xacked = True
                event.last_error = ""
                submitted += 1
                self._stats["submitted"] += 1
                self._stats["xacked"] += 1
            else:
                event.state = IngestState.ERROR
                event.last_error = task_id
                self._stats["errors"] += 1

                # Exponential backoff на ошибку
                if "504" in task_id or "Timeout" in task_id or "Connection" in task_id:
                    self._apply_backoff()

        return submitted

    def feed_standalone(self, s3_uri: str, project_key: str) -> Tuple[bool, str]:
        """Отправить один SARIF отчёт напрямую (в обход очереди)."""
        return self._sonar.submit_report(project_key, s3_uri)

    # ── Poll & Feed cycle ────────────────────────────────────────────────────

    def poll_and_feed(self) -> Tuple[int, int]:
        """Один цикл: poll → health check → feed.

        Returns:
            (polled, submitted).
        """
        events = self.poll_queue()
        if not events:
            return 0, 0

        healthy, pending = self.check_sonar_health()
        if not healthy:
            logger.info("SonarQube overloaded (pending=%d). Skipping feed.", pending)
            return len(events), 0

        # Rate-limiting: пауза между подачами
        time.sleep(self._rate_limit_delay_s)

        submitted = self.feed_events(events)
        return len(events), submitted

    # ── Query ────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def get_event(self, event_id: str) -> IngestEvent | None:
        return self._events.get(event_id)

    def list_events(self, state: IngestState | None = None) -> List[IngestEvent]:
        events = list(self._events.values())
        if state:
            events = [e for e in events if e.state == state]
        return events

    def pending_events(self) -> List[IngestEvent]:
        return self.list_events(IngestState.QUEUED)

    def active_count(self) -> int:
        return sum(
            1 for e in self._events.values()
            if e.state in (IngestState.QUEUED, IngestState.PENDING_CE)
        )

    def reset_backoff(self) -> None:
        self._stats["backoffs"] = 0
        self._paused_until = 0.0


# ── Convenience factories ───────────────────────────────────────────────────

def simulate_sonar_overload(sonar: MockSonarQubeBackend, task_count: int = 5) -> None:
    """COS-074: симуляция перегрузки SonarQube CE."""
    sonar.sim_overload = True


def simulate_sonar_crash(sonar: MockSonarQubeBackend) -> None:
    """COS-074: симуляция недоступности SonarQube."""
    sonar.sim_unavailable = True


def simulate_sonar_timeout(sonar: MockSonarQubeBackend) -> None:
    """COS-074: симуляция 504 Gateway Timeout."""
    sonar.sim_timeout = True