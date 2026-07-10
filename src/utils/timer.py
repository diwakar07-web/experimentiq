"""
ExperimentIQ — Execution Timer Utility

Purpose:
    Provides a context manager and decorator for measuring execution time
    of pipeline stages. Logs start, end, and duration at INFO level.

Design:
    - StageTimer: context manager for use with `with` blocks.
    - timed: decorator for functions that should be auto-timed.
    - Both emit structured log entries suitable for audit trails.

Dependencies:
    Standard library only (time, logging, functools, contextlib).

Inputs:
    Stage name string.

Outputs:
    Logged timing information; elapsed seconds accessible from context.
"""

from __future__ import annotations

import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class StageTimer:
    """
    Context manager that measures and logs the wall-clock duration of a pipeline stage.

    Usage:
        with StageTimer("Data Generation") as timer:
            generate_data()
        print(timer.elapsed_seconds)

    Attributes:
        stage_name: Human-readable name of the stage being timed.
        elapsed_seconds: Duration in seconds (set after __exit__).
        success: True if the stage completed without exception.
    """

    def __init__(self, stage_name: str, logger_instance: Optional[logging.Logger] = None) -> None:
        """
        Initialise the timer.

        Args:
            stage_name: Human-readable name of the stage being measured.
            logger_instance: Optional custom logger. Defaults to module logger.
        """
        self.stage_name = stage_name
        self._logger = logger_instance or logger
        self._start_time: float = 0.0
        self.elapsed_seconds: float = 0.0
        self.success: bool = False

    def __enter__(self) -> "StageTimer":
        """Record start time and log stage beginning."""
        self._start_time = time.perf_counter()
        self._logger.info("> Starting stage: %s", self.stage_name)
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> bool:
        """Record end time, compute elapsed duration, and log result."""
        self.elapsed_seconds = time.perf_counter() - self._start_time
        self.success = exc_type is None

        if self.success:
            self._logger.info(
                "[OK] Completed stage: %s | duration=%.3fs",
                self.stage_name,
                self.elapsed_seconds,
            )
        else:
            self._logger.error(
                "[FAIL] Failed stage: %s | duration=%.3fs | error=%s",
                self.stage_name,
                self.elapsed_seconds,
                exc_type.__name__ if exc_type else "Unknown",
            )

        # Do not suppress exceptions
        return False

    @property
    def elapsed_ms(self) -> float:
        """Return elapsed time in milliseconds."""
        return self.elapsed_seconds * 1000.0

    def __repr__(self) -> str:
        return (
            f"StageTimer(stage={self.stage_name!r}, "
            f"elapsed={self.elapsed_seconds:.3f}s, success={self.success})"
        )


@contextmanager
def timed_block(stage_name: str) -> Generator[StageTimer, None, None]:
    """
    Context manager alias for StageTimer (functional style).

    Usage:
        with timed_block("SQL Execution") as t:
            run_sql()
        print(f"Took {t.elapsed_seconds:.2f}s")

    Args:
        stage_name: Human-readable name of the block being timed.

    Yields:
        StageTimer instance with elapsed_seconds populated on exit.
    """
    timer = StageTimer(stage_name)
    with timer:
        yield timer


def timed(stage_name: Optional[str] = None) -> Callable[[F], F]:
    """
    Decorator that times a function call and logs its duration.

    Usage:
        @timed("Data Generation")
        def generate():
            ...

        @timed()  # Uses function name as stage name
        def load_data():
            ...

    Args:
        stage_name: Optional display name. Defaults to the function's __qualname__.

    Returns:
        Decorated function with automatic timing and logging.
    """
    def decorator(func: F) -> F:
        display_name = stage_name or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with StageTimer(display_name):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


class PipelineTimer:
    """
    Tracks timing of multiple pipeline stages in sequence.

    Usage:
        pt = PipelineTimer("Full Pipeline")
        with pt.stage("Generation"):
            generate()
        with pt.stage("Loading"):
            load()
        pt.log_summary()

    Attributes:
        pipeline_name: Name of the overall pipeline.
        stages: Ordered list of (stage_name, elapsed_seconds, success) tuples.
    """

    def __init__(self, pipeline_name: str) -> None:
        """
        Initialise the pipeline timer.

        Args:
            pipeline_name: Human-readable name of the overall pipeline.
        """
        self.pipeline_name = pipeline_name
        self._pipeline_start: float = time.perf_counter()
        self.stages: list[tuple[str, float, bool]] = []

    @contextmanager
    def stage(self, stage_name: str) -> Generator[StageTimer, None, None]:
        """
        Context manager that times a pipeline stage and records the result.

        Args:
            stage_name: Human-readable name of the stage.

        Yields:
            StageTimer with elapsed time populated on exit.
        """
        timer = StageTimer(stage_name)
        with timer:
            yield timer
        self.stages.append((stage_name, timer.elapsed_seconds, timer.success))

    @property
    def total_elapsed_seconds(self) -> float:
        """Return total elapsed time since pipeline start."""
        return time.perf_counter() - self._pipeline_start

    def log_summary(self) -> None:
        """Log a formatted summary of all stage timings."""
        total = self.total_elapsed_seconds
        logger.info("=" * 60)
        logger.info("Pipeline Summary: %s | total=%.2fs", self.pipeline_name, total)
        logger.info("=" * 60)

        for i, (name, elapsed, success) in enumerate(self.stages, 1):
            status = "[OK]" if success else "[FAIL]"
            pct = (elapsed / total * 100) if total > 0 else 0
            logger.info(
                "  %s  Step %2d: %-40s %.2fs (%4.1f%%)",
                status,
                i,
                name,
                elapsed,
                pct,
            )

        logger.info("=" * 60)
