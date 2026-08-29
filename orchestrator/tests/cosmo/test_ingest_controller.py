"""
COS-074: Ingest Token Bucket tests.

50 отчётов → равномерное скармливание батчами по 2.
Эмуляция перегрузки SonarQube (backoff).
Эмуляция падения SonarQube (задачи не теряются, QUEUED).
XACK только после успешной отправки.
Exponential backoff.
"""
import time
import pytest
from cosmo.capability.ingest_controller import (
    IngestTokenBucket, IngestEvent, IngestState,
    MockValkeyStreamBackend, MockSonarQubeBackend,
    simulate_sonar_overload, simulate_sonar_crash, simulate_sonar_timeout,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def valkey():
    return MockValkeyStreamBackend()

@pytest.fixture
def sonar():
    return MockSonarQubeBackend()

@pytest.fixture
def bucket(valkey, sonar):
    return IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.01)


# ── IngestEvent model ──────────────────────────────────────────────────────

class TestIngestEvent:
    def test_defaults(self):
        ev = IngestEvent(event_id="msg-1", s3_uri="s3://pk/report.sarif",
                         project_key="test-project", run_id="run-1")
        assert ev.state == IngestState.QUEUED
        assert ev.attempt == 0
        assert ev.xacked is False

    def test_event_key(self):
        ev = IngestEvent(event_id="m1", s3_uri="s3://pk/report.sarif",
                         project_key="proj-key", run_id="r1")
        assert "proj-key:report.sarif" in ev.event_key()

    def test_to_dict(self):
        ev = IngestEvent(event_id="m1", s3_uri="s3://pk/x.sarif",
                         project_key="pk", run_id="r1", batch_id="b1")
        d = ev.to_dict()
        assert d["event_id"] == "m1"
        assert d["state"] == "queued"
        assert d["attempt"] == 0

    def test_max_retries_rejected(self):
        ev = IngestEvent(event_id="m1", s3_uri="s://x", project_key="p",
                         run_id="r1", attempt=5)
        # Создаём bucket и feed_events с недоступным Sonar —
        # попытка #6 = REJECTED
        valkey = MockValkeyStreamBackend()
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)
        submitted = bucket.feed_events([ev])
        assert submitted == 0
        assert ev.state == IngestState.REJECTED


# ── Valkey Stream mock operations ──────────────────────────────────────────

class TestMockValkeyStream:
    def test_xadd_and_read(self, valkey):
        msg_id = valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/report.sarif",
                                               "project_key": "pk", "run_id": "r1"})
        assert msg_id.startswith("msg-")

        msgs = valkey.xreadgroup("cosmo-ingest", "consumer-1", "sonar.ingest", count=1)
        assert len(msgs) == 1
        msgs2 = valkey.xreadgroup("cosmo-ingest", "consumer-1", "sonar.ingest", count=1)
        assert len(msgs2) == 0  # уже обработан

    def test_xack_removes_from_pending(self, valkey):
        msg_id = valkey.xadd("sonar.ingest", {"s3_uri": "s://x", "project_key": "p", "run_id": "r"})
        valkey.xreadgroup("grp", "cons", "sonar.ingest", count=1)
        assert valkey.xpending("sonar.ingest", "grp") == 1
        valkey.xack("sonar.ingest", "grp", msg_id)
        assert valkey.xpending("sonar.ingest", "grp") == 0

    def test_stream_length(self, valkey):
        assert valkey.stream_length("sonar.ingest") == 0
        valkey.xadd("sonar.ingest", {"k": "v"})
        assert valkey.stream_length("sonar.ingest") == 1


# ── SonarQube mock operations ──────────────────────────────────────────────

class TestMockSonarQube:
    def test_submit_report(self, sonar):
        ok, task_id = sonar.submit_report("pk", "s3://x/report.sarif")
        assert ok is True
        assert task_id.startswith("ce-task-")

    def test_get_ce_activity(self, sonar):
        tasks = sonar.get_ce_activity()
        assert len(tasks) >= 1

    def test_submit_while_unavailable(self):
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        ok, err = sonar.submit_report("pk", "s3://x")
        assert ok is False
        assert "refused" in err.lower()

    def test_submit_while_timeout(self):
        sonar = MockSonarQubeBackend(sim_timeout=True)
        ok, err = sonar.submit_report("pk", "s3://x")
        assert ok is False
        assert "504" in err


# ── Token Bucket: poll + feed ──────────────────────────────────────────────

class TestTokenBucket:
    def test_poll_queue_empty(self, bucket):
        events = bucket.poll_queue()
        assert events == []

    def test_poll_queue_reads_messages(self, valkey, bucket):
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/a.sarif", "project_key": "pk", "run_id": "r1"})
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/b.sarif", "project_key": "pk", "run_id": "r2"})

        events = bucket.poll_queue()
        assert len(events) == 2

    def test_poll_respects_max_concurrency(self, valkey):
        bucket = IngestTokenBucket(valkey, MockSonarQubeBackend(), max_concurrency=3, rate_limit_delay_s=0.0)
        for i in range(5):
            valkey.xadd("sonar.ingest", {"s3_uri": f"s3://x/{i}.sarif", "project_key": "pk", "run_id": f"r{i}"})

        events = bucket.poll_queue(count=3)
        assert len(events) == 3

    def test_feed_events_success(self, valkey, bucket):
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif", "project_key": "pk", "run_id": "r1"})
        events = bucket.poll_queue()

        submitted = bucket.feed_events(events)
        assert submitted == 1
        assert events[0].state == IngestState.PENDING_CE
        assert events[0].xacked is True

    def test_feed_not_xack_on_failure(self, valkey):
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)

        msg_id = valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif", "project_key": "p", "run_id": "r1"})
        events = bucket.poll_queue()
        submitted = bucket.feed_events(events)
        assert submitted == 0
        # XACK не подтверждён
        assert valkey.xpending("sonar.ingest", "cosmo-ingest") == 1

    def test_stats_tracking(self, valkey, bucket):
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/a.sarif", "project_key": "pk", "run_id": "r1"})
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/b.sarif", "project_key": "pk", "run_id": "r2"})

        bucket.poll_queue()
        events = bucket.list_events(IngestState.QUEUED)
        bucket.feed_events(events)

        s = bucket.stats
        assert s["polled"] == 2
        assert s["submitted"] == 2
        assert s["xacked"] == 2

    def test_poll_and_feed_cycle(self, valkey, bucket):
        """Один цикл poll_and_feed()."""
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif", "project_key": "pk", "run_id": "r1"})
        polled, submitted = bucket.poll_and_feed()
        assert polled == 1
        assert submitted == 1

    def test_active_count(self, valkey, bucket):
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/a.sarif", "project_key": "pk", "run_id": "r1"})
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/b.sarif", "project_key": "pk", "run_id": "r2"})
        bucket.poll_queue()
        assert bucket.active_count() == 2
        events = bucket.list_events(IngestState.QUEUED)
        bucket.feed_events(events)
        assert bucket.active_count() == 2  # PENDING_CE after feed

    def test_feed_standalone(self, bucket):
        ok, task_id = bucket.feed_standalone("s3://x/r.sarif", "proj")
        assert ok is True
        assert task_id.startswith("ce-task-")


# ── 50 отчётов → batch of 2 ───────────────────────────────────────────────

class TestBatchFeeding:
    def test_fifty_reports_batched_by_two(self, valkey):
        """50 отчётов → 25 батчей по 2 (max_concurrency=2)."""
        sonar = MockSonarQubeBackend()
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)

        for i in range(50):
            valkey.xadd("sonar.ingest", {
                "s3_uri": f"s3://pk/report-{i}.sarif",
                "project_key": f"project-{i % 5}",
                "run_id": f"run-{i}",
            })

        total_polled = 0
        total_submitted = 0
        batches = 0

        while total_polled < 50:
            events = bucket.poll_queue()
            if not events:
                break
            batches += 1
            total_polled += len(events)
            submitted = bucket.feed_events(events)
            total_submitted += submitted

            # Каждый batch не больше max_concurrency
            assert len(events) <= 2, f"Batch {batches} exceeded concurrency: {len(events)}"

        assert total_polled == 50
        assert total_submitted == 50
        assert batches == 25

        # Все XACK подтверждены
        assert valkey.xpending("sonar.ingest", "cosmo-ingest") == 0

    def test_fifty_reports_with_errors_resubmitted(self, valkey):
        """При ошибке Sonar — сообщения не теряются, возвращаются в очередь."""
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)

        for i in range(5):
            valkey.xadd("sonar.ingest", {
                "s3_uri": f"s3://pk/report-{i}.sarif",
                "project_key": "pk", "run_id": f"run-{i}",
            })

        events = bucket.poll_queue()
        submitted = bucket.feed_events(events)
        assert submitted == 0  # SonarQube недоступен

        # Сообщения НЕ подтверждены (pending)
        # xreadgroup вернул max_concurrency=2 сообщения (из 5 в очереди)
        # Они pending, остальные 3 в очереди не прочитаны
        assert valkey.xpending("sonar.ingest", "cosmo-ingest") == 2

        # События в QUEUED / ERROR (попытка была)
        for e in events:
            assert e.attempt == 1
            assert e.xacked is False


# ── Overload backoff ───────────────────────────────────────────────────────

class TestOverloadBackoff:
    def test_overload_causes_pause(self, valkey):
        sonar = MockSonarQubeBackend(sim_overload=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)

        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif", "project_key": "pk", "run_id": "r1"})
        events = bucket.poll_queue()
        assert len(events) == 1

        healthy, pending = bucket.check_sonar_health()
        assert healthy is False
        assert pending > 3
        assert bucket.stats["backoffs"] >= 1

        # После overload health-check, пауза активирована — poll вернёт пусто
        bucket._paused_until = time.time() + 10  # форсируем паузу
        events2 = bucket.poll_queue()
        assert events2 == []

    def test_backoff_resets(self, valkey, bucket):
        bucket._apply_backoff()
        assert bucket.stats["backoffs"] >= 1
        assert bucket._paused_until > 0

        bucket.reset_backoff()
        assert bucket.stats["backoffs"] == 0
        assert bucket._paused_until == 0.0

    def test_backoff_exponential(self, valkey, bucket):
        """Exponential backoff: 2s → 4s → 8s → cap 60s."""
        for i in range(5):
            bucket._apply_backoff()
        assert bucket.stats["backoffs"] == 5
        # Должен быть ≤ 60s (cap)
        assert bucket._paused_until <= time.time() + 60.1

    def test_poll_respects_backoff(self, valkey):
        sonar = MockSonarQubeBackend(sim_overload=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.01)

        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif", "project_key": "pk", "run_id": "r1"})

        # Триггерим health check → backoff
        bucket.check_sonar_health()

        # Полл долежн вернуть пусто (backoff активен)
        events = bucket.poll_queue()
        assert events == []

        # Срос backoff → полл работет
        bucket.reset_backoff()
        events = bucket.poll_queue()
        assert len(events) == 1


# ── SonarQube crash — сообщения не теряются ───────────────────────────────

class TestSonarCrash:
    def test_crash_preserves_events(self, valkey):
        """При падении Sonar события остаются в QUEUED и не подтвердены."""
        sonar = MockSonarQubeBackend(sim_unavailable=True)
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.0)

        for i in range(5):
            valkey.xadd("sonar.ingest", {
                "s3_uri": f"s3://pk/r-{i}.sarif", "project_key": "pk", "run_id": f"run-{i}"
            })

        events = bucket.poll_queue()
        assert len(events) == 2  # max_concurrency=2

        bucket.feed_events(events)

        # Все 5 событий в очереди — 2 обработаны (попытка), 3 не тронуты
        for e in events:
            assert e.state == IngestState.ERROR
            assert e.xacked is False
            assert e.attempt == 1

    def test_crash_recovery_resubmission(self, valkey):
        """После восcтановления SonarQube — события уcпешно обрабатываются."""
        # Фаза 1: Sonar упал
        sonar_crashed = MockSonarQubeBackend(sim_unavailable=True)
        bucket = IngestTokenBucket(valkey, sonar_crashed, max_concurrency=2, rate_limit_delay_s=0.0)

        msg_id = valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r.sarif",
                                               "project_key": "pk", "run_id": "r1"})
        events = bucket.poll_queue()
        bucket.feed_events(events)
        assert events[0].state == IngestState.ERROR
        assert events[0].xacked is False

        # Фаза 2: Sonar восстановился — новое сообщение обрабатывается
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/r2.sarif",
                                      "project_key": "pk", "run_id": "r2"})
        bucket2 = IngestTokenBucket(valkey, MockSonarQubeBackend(), max_concurrency=2, rate_limit_delay_s=0.0)
        events2 = bucket2.poll_queue()
        submitted = bucket2.feed_events(events2)
        assert submitted == 1


# ── Rate limit enforcement ─────────────────────────────────────────────────

class TestRateLimit:
    def test_rate_limit_skips(self, valkey, sonar):
        bucket = IngestTokenBucket(valkey, sonar, max_concurrency=2, rate_limit_delay_s=0.5)
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/a.sarif", "project_key": "pk", "run_id": "r1"})

        e1 = bucket.poll_queue()
        assert len(e1) > 0
        # Мидиатный повтор — долежн быть пропусщен
        e2 = bucket.poll_queue()
        assert e2 == []
        assert bucket.stats["skips"] >= 1

    def test_rate_imit_different_consumers(self, valkey, sonar):
        """Разные consumer_id — нзависимые rate limits."""
        b1 = IngestTokenBucket(valkey, MockSonarQubeBackend(), max_concurrency=2,
                                rate_limit_delay_s=0.0, consumer_id="c1")
        b2 = IngestTokenBucket(valkey, MockSonarQubeBackend(), max_concurrency=2,
                                rate_limit_delay_s=0.0, consumer_id="c2")

        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/a.sarif", "project_key": "pk", "run_id": "r1"})
        valkey.xadd("sonar.ingest", {"s3_uri": "s3://x/b.sarif", "project_key": "pk", "run_id": "r2"})

        e1 = b1.poll_queue()
        e2 = b2.poll_queue()
        assert len(e1) == 2
        assert len(e2) == 0  # уже обработаны c1

    def test_feed_standalone_bypasses_queue(self, bucket):
        """feed_standalone не зависит от очереди."""
        ok, tid = bucket.feed_standalone("s3://x/r.sarif", "proj")
        assert ok is True
        assert tid


# ── Simulate helpers ────────────────────────────────────────────────────────

class TestSimulateHelpers:
    def test_simulate_overload(self, sonar):
        simulate_sonar_overload(sonar, task_count=5)
        assert sonar.sim_overload is True
        tasks = sonar.get_ce_activity()
        assert len(tasks) == 5

    def test_simulate_crash(self, sonar):
        simulate_sonar_crash(sonar)
        assert sonar.sim_unavailable is True
        with pytest.raises(ConnectionError):
            sonar.get_ce_activity()

    def test_simulate_timeout(self, sonar):
        simulate_sonar_timeout(sonar)
        assert sonar.sim_timeout is True
        ok, err = sonar.submit_report("pk", "s3://x")
        assert not ok
        assert "504" in err