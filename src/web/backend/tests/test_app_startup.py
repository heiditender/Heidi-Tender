from __future__ import annotations

import pytest

from app import main as app_main


def test_run_startup_step_with_retry_recovers_from_transient_failure() -> None:
    calls = {"count": 0}
    current_time = {"value": 0.0}
    sleeps: list[float] = []

    def flaky_step() -> None:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("mysql not ready")

    def monotonic_fn() -> float:
        return current_time["value"]

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        current_time["value"] += seconds

    app_main._run_startup_step_with_retry(
        "seed_default_rules",
        flaky_step,
        timeout_seconds=5.0,
        interval_seconds=1.0,
        monotonic_fn=monotonic_fn,
        sleep_fn=sleep_fn,
    )

    assert calls["count"] == 3
    assert sleeps == [1.0, 1.0]


def test_run_startup_step_with_retry_raises_after_timeout() -> None:
    current_time = {"value": 0.0}
    sleeps: list[float] = []

    def failing_step() -> None:
        raise RuntimeError("postgres not ready")

    def monotonic_fn() -> float:
        return current_time["value"]

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        current_time["value"] += seconds

    with pytest.raises(RuntimeError) as excinfo:
        app_main._run_startup_step_with_retry(
            "runtime_database_bootstrap",
            failing_step,
            timeout_seconds=2.5,
            interval_seconds=1.0,
            monotonic_fn=monotonic_fn,
            sleep_fn=sleep_fn,
        )

    assert "runtime_database_bootstrap" in str(excinfo.value)
    assert "failed after" in str(excinfo.value)
    assert sleeps == [1.0, 1.0, 1.0]
