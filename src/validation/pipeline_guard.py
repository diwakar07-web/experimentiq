"""
ExperimentIQ — Pipeline Guard
==============================

Purpose:
    Pre-flight checks executed before any pipeline stage runs. Verifies
    that the environment is correctly configured and ready for data
    generation and loading. Used by run_pipeline.py before invoking
    any generator, loader, or analytics stage.

Design:
    - PipelineGuard is stateless; all checks are idempotent.
    - Each check is independent and logs its own result.
    - run_all_checks() returns a dict so callers can decide which
      failures are blocking vs. advisory.
    - Database connectivity is retried with exponential back-off.

Dependencies:
    - psycopg2 >= 2.9
    - pydantic-settings >= 2.0
    - shutil (stdlib)

Usage:
    from src.validation.pipeline_guard import PipelineGuard
    from config import get_settings

    guard = PipelineGuard(settings=get_settings())
    results = guard.run_all_checks()
    if not all(results.values()):
        failed = [k for k, v in results.items() if not v]
        raise RuntimeError(f"Pre-flight checks failed: {failed}")
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation ranges for settings fields
# ---------------------------------------------------------------------------

SETTINGS_VALIDATION_RULES: dict[str, dict[str, Any]] = {
    "generator.num_users": {"min": 1_000, "max": 5_000_000},
    "generator.experiment_days": {"min": 7, "max": 365},
    "generator.baseline_conversion_rate": {"min": 0.001, "max": 0.5},
    "generator.variant_uplift": {"min": -0.5, "max": 2.0},
    "generator.variant_split": {"min": 0.1, "max": 0.9},
    "generator.max_events_per_session": {"min": 2, "max": 100},
    "generator.avg_sessions_per_user": {"min": 1.0, "max": 20.0},
    "statistics.alpha": {"min": 0.001, "max": 0.2},
    "statistics.power_target": {"min": 0.5, "max": 0.99},
    "statistics.srm_alpha": {"min": 0.001, "max": 0.1},
    "database.port": {"min": 1, "max": 65535},
    "database.bulk_insert_chunk_size": {"min": 100, "max": 100_000},
}


class PipelineGuard:
    """
    Pre-flight environment checker for the ExperimentIQ pipeline.

    Performs connectivity, configuration, disk space, and directory
    checks before pipeline stages are invoked. All checks are safe to
    run multiple times (idempotent) and do not modify any system state.

    Attributes:
        settings:            The application Settings instance.
        db_retry_attempts:   Number of times to retry the DB connectivity check.
        db_retry_delay_s:    Initial delay (seconds) between DB retry attempts.
                             Each retry doubles this value (exponential back-off).
        required_disk_gb:    Default minimum free disk space in GB.
    """

    def __init__(
        self,
        settings: Any = None,  # config.settings.Settings
        db_retry_attempts: int = 3,
        db_retry_delay_s: float = 2.0,
    ) -> None:
        """
        Initialise PipelineGuard.

        Args:
            settings:           Application Settings instance. If None,
                                get_settings() is called automatically.
            db_retry_attempts:  How many times to retry DB connectivity.
            db_retry_delay_s:   Initial wait between retries (doubles each attempt).
        """
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self.settings = settings
        self.db_retry_attempts = db_retry_attempts
        self.db_retry_delay_s = db_retry_delay_s
        logger.debug(
            "PipelineGuard initialised | DB host: %s | retries: %d",
            self.settings.database.host,
            self.db_retry_attempts,
        )

    # ------------------------------------------------------------------
    # check_database_connectivity
    # ------------------------------------------------------------------

    def check_database_connectivity(self) -> bool:
        """
        Verify that a PostgreSQL connection can be established using the
        configured credentials.

        The check attempts up to ``db_retry_attempts`` connections with
        exponential back-off between attempts. A simple ``SELECT 1``
        query is executed to confirm the server is responsive.

        Returns:
            True if a connection is successfully established; False otherwise.
        """
        import psycopg2
        from psycopg2 import OperationalError

        dsn = self.settings.database.psycopg2_dsn
        delay = self.db_retry_delay_s

        for attempt in range(1, self.db_retry_attempts + 1):
            try:
                logger.debug(
                    "DB connectivity check — attempt %d/%d to %s:%d/%s",
                    attempt,
                    self.db_retry_attempts,
                    self.settings.database.host,
                    self.settings.database.port,
                    self.settings.database.name,
                )
                conn = psycopg2.connect(dsn, connect_timeout=10)
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
                conn.close()
                logger.info(
                    "[OK] Database connectivity: OK "
                    "(host=%s, db=%s, attempt=%d)",
                    self.settings.database.host,
                    self.settings.database.name,
                    attempt,
                )
                return True
            except OperationalError as exc:
                logger.warning(
                    "DB connection attempt %d/%d failed: %s",
                    attempt,
                    self.db_retry_attempts,
                    exc,
                )
                if attempt < self.db_retry_attempts:
                    logger.debug("Retrying in %.1f seconds …", delay)
                    time.sleep(delay)
                    delay *= 2  # Exponential back-off
            except Exception as exc:
                logger.error("Unexpected error during DB connectivity check: %s", exc)
                return False

        logger.error(
            "[FAIL] Database connectivity: FAILED after %d attempts "
            "(host=%s, db=%s)",
            self.db_retry_attempts,
            self.settings.database.host,
            self.settings.database.name,
        )
        return False

    # ------------------------------------------------------------------
    # check_configuration_valid
    # ------------------------------------------------------------------

    def check_configuration_valid(self) -> bool:
        """
        Validate that all settings values are within their expected ranges
        and are logically consistent.

        This check does not re-run Pydantic validation (which happens at
        import time); instead it applies additional cross-field business
        rules such as ensuring experiment_start_date < experiment_end_date
        and that the number of users is achievable given session parameters.

        Returns:
            True if all configuration checks pass; False if any fail.
        """
        all_valid = True
        s = self.settings

        logger.debug("Starting configuration validity checks …")

        def _check(condition: bool, name: str, detail: str) -> None:
            nonlocal all_valid
            if not condition:
                logger.error("[FAIL] Config check FAILED [%s]: %s", name, detail)
                all_valid = False
            else:
                logger.debug("  [OK] Config check passed [%s]", name)

        # --- Numeric range checks (cross-checks against SETTINGS_VALIDATION_RULES) ---
        _check(
            1_000 <= s.generator.num_users <= 5_000_000,
            "num_users_range",
            f"num_users={s.generator.num_users} must be in [1 000, 5 000 000]",
        )
        _check(
            7 <= s.generator.experiment_days <= 365,
            "experiment_days_range",
            f"experiment_days={s.generator.experiment_days} must be in [7, 365]",
        )
        _check(
            0.001 <= s.generator.baseline_conversion_rate <= 0.5,
            "baseline_conversion_rate_range",
            f"baseline_conversion_rate={s.generator.baseline_conversion_rate}",
        )
        _check(
            -0.5 <= s.generator.variant_uplift <= 2.0,
            "variant_uplift_range",
            f"variant_uplift={s.generator.variant_uplift}",
        )
        _check(
            0.1 <= s.generator.variant_split <= 0.9,
            "variant_split_range",
            f"variant_split={s.generator.variant_split}",
        )
        _check(
            2 <= s.generator.max_events_per_session <= 100,
            "max_events_per_session_range",
            f"max_events_per_session={s.generator.max_events_per_session}",
        )
        _check(
            1.0 <= s.generator.avg_sessions_per_user <= 20.0,
            "avg_sessions_per_user_range",
            f"avg_sessions_per_user={s.generator.avg_sessions_per_user}",
        )
        _check(
            0.001 <= s.statistics.alpha <= 0.2,
            "alpha_range",
            f"alpha={s.statistics.alpha}",
        )
        _check(
            0.5 <= s.statistics.power_target <= 0.99,
            "power_target_range",
            f"power_target={s.statistics.power_target}",
        )
        _check(
            0.001 <= s.statistics.srm_alpha <= 0.1,
            "srm_alpha_range",
            f"srm_alpha={s.statistics.srm_alpha}",
        )
        _check(
            1 <= s.database.port <= 65535,
            "db_port_range",
            f"db_port={s.database.port}",
        )
        _check(
            100 <= s.database.bulk_insert_chunk_size <= 100_000,
            "bulk_insert_chunk_size_range",
            f"bulk_insert_chunk_size={s.database.bulk_insert_chunk_size}",
        )

        # --- Cross-field logical checks ---

        # Experiment start must be before experiment end
        _check(
            s.generator.experiment_start_date < s.generator.experiment_end_date,
            "experiment_date_order",
            f"experiment_start_date ({s.generator.experiment_start_date}) must be "
            f"before experiment_end_date ({s.generator.experiment_end_date})",
        )

        # Variant conversion rate must be a sensible positive number
        variant_cr = s.generator.baseline_conversion_rate * (1 + s.generator.variant_uplift)
        _check(
            0 < variant_cr <= 1.0,
            "variant_conversion_rate_valid",
            f"Computed variant_conversion_rate={variant_cr:.4f} is not in (0, 1]. "
            f"Check baseline_conversion_rate and variant_uplift.",
        )

        # correction_method must be a known value
        _check(
            s.statistics.correction_method in {"bonferroni", "benjamini_hochberg", "none"},
            "correction_method_valid",
            f"Unknown correction_method='{s.statistics.correction_method}'",
        )

        # Database credentials must not be empty
        for attr in ("host", "name", "user", "password"):
            val = getattr(s.database, attr, "")
            _check(
                bool(val and str(val).strip()),
                f"db_{attr}_not_empty",
                f"database.{attr} must not be empty",
            )

        status = "VALID" if all_valid else "INVALID"
        logger.info("[OK] Configuration validity: %s", status) if all_valid else logger.error(
            "[FAIL] Configuration validity: %s", status
        )
        return all_valid

    # ------------------------------------------------------------------
    # check_output_directories_writable
    # ------------------------------------------------------------------

    def check_output_directories_writable(self) -> bool:
        """
        Check that all configured output directories exist and are writable.

        Attempts to create a temporary file inside each directory and
        immediately removes it. Does not modify any real data.

        Returns:
            True if all directories are writable; False if any are not.
        """
        all_ok = True
        s = self.settings

        directories: list[Path] = [
            s.output.raw_path(),
            s.output.processed_path(),
            s.output.exports_path(),
            s.output.reports_path(),
        ]

        # Also check the log file directory if configured
        log_path = s.logging.log_file_path()
        if log_path is not None:
            directories.append(log_path.parent)

        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                probe_file = directory / ".write_probe"
                probe_file.write_text("probe")
                probe_file.unlink()
                logger.debug("  [OK] Directory writable: %s", directory)
            except PermissionError as exc:
                logger.error(
                    "[FAIL] Directory not writable: %s — %s", directory, exc
                )
                all_ok = False
            except OSError as exc:
                logger.error(
                    "[FAIL] Directory error: %s — %s", directory, exc
                )
                all_ok = False

        if all_ok:
            logger.info(
                "[OK] Output directories: all %d directories are writable",
                len(directories),
            )
        else:
            logger.error("[FAIL] Output directories: one or more directories are not writable")

        return all_ok

    # ------------------------------------------------------------------
    # check_disk_space_available
    # ------------------------------------------------------------------

    def check_disk_space_available(self, required_gb: float = 5.0) -> bool:
        """
        Check whether sufficient free disk space is available on the
        filesystem where output data will be written.

        The check is performed against the raw data output directory.
        The required space should cover: generated CSVs + database WAL
        overhead + report PDFs + log files.

        Args:
            required_gb: Minimum free space required in gigabytes.
                         Defaults to 5.0 GB.

        Returns:
            True if free space >= required_gb; False otherwise.
        """
        output_path = self.settings.output.raw_path()

        try:
            # Walk up until we find an existing ancestor
            probe_path = output_path
            while not probe_path.exists():
                probe_path = probe_path.parent
                if probe_path == probe_path.parent:
                    # Reached filesystem root without finding an existing dir
                    logger.error(
                        "[FAIL] Disk space check: could not determine filesystem "
                        "root from %s", output_path
                    )
                    return False

            disk_usage = shutil.disk_usage(probe_path)
            free_gb = disk_usage.free / (1024 ** 3)
            total_gb = disk_usage.total / (1024 ** 3)

            if free_gb >= required_gb:
                logger.info(
                    "[OK] Disk space: %.1f GB free / %.1f GB total "
                    "(required: %.1f GB)",
                    free_gb,
                    total_gb,
                    required_gb,
                )
                return True
            else:
                logger.error(
                    "[FAIL] Disk space: only %.1f GB free / %.1f GB total — "
                    "%.1f GB required. Free up disk space before proceeding.",
                    free_gb,
                    total_gb,
                    required_gb,
                )
                return False

        except FileNotFoundError as exc:
            logger.error("[FAIL] Disk space check: path not found — %s", exc)
            return False
        except PermissionError as exc:
            logger.error("[FAIL] Disk space check: permission denied — %s", exc)
            return False
        except Exception as exc:
            logger.error("[FAIL] Disk space check: unexpected error — %s", exc)
            return False

    # ------------------------------------------------------------------
    # run_all_checks
    # ------------------------------------------------------------------

    def run_all_checks(self, required_disk_gb: float = 5.0) -> dict[str, bool]:
        """
        Execute all pre-flight checks in sequence and return a result map.

        The checks are ordered from fastest/cheapest to slowest/most
        expensive:
            1. Configuration validity  (pure Python — fastest)
            2. Output directories      (filesystem I/O — fast)
            3. Disk space              (filesystem stat — fast)
            4. Database connectivity   (network I/O with retries — slowest)

        Args:
            required_disk_gb: Minimum free disk space to require (GB).

        Returns:
            A dictionary mapping check_name (str) → result (bool).
            All True means the environment is ready to run the pipeline.

        Example::

            results = guard.run_all_checks()
            # {
            #   "configuration_valid": True,
            #   "output_directories_writable": True,
            #   "disk_space_available": True,
            #   "database_connectivity": True,
            # }
        """
        logger.info("=" * 60)
        logger.info("ExperimentIQ Pipeline — Pre-flight Checks")
        logger.info("=" * 60)

        results: dict[str, bool] = {}

        # 1. Configuration validity
        logger.info("Running check: configuration_valid …")
        results["configuration_valid"] = self.check_configuration_valid()

        # 2. Output directories writable
        logger.info("Running check: output_directories_writable …")
        results["output_directories_writable"] = self.check_output_directories_writable()

        # 3. Disk space
        logger.info("Running check: disk_space_available (%.1f GB required) …", required_disk_gb)
        results["disk_space_available"] = self.check_disk_space_available(
            required_gb=required_disk_gb
        )

        # 4. Database connectivity (most expensive — run last)
        logger.info("Running check: database_connectivity …")
        results["database_connectivity"] = self.check_database_connectivity()

        # Summary
        passed = sum(1 for v in results.values() if v)
        failed = len(results) - passed
        overall_status = "ALL PASSED" if failed == 0 else f"{failed} FAILED"

        logger.info("=" * 60)
        logger.info("Pre-flight Check Results — %s", overall_status)
        for check_name, result in results.items():
            status_icon = "[OK]" if result else "[FAIL]"
            logger.info("  %s %s: %s", status_icon, check_name, "PASS" if result else "FAIL")
        logger.info("=" * 60)

        return results
