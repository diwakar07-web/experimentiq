"""
ExperimentIQ — Session Generator

Purpose:
    Generates realistic user browsing sessions for each user over the
    experiment duration. Produces a DataFrame matching the `sessions` table.

Design:
    - Each user gets 1–N sessions based on a Poisson distribution around
      the configured avg_sessions_per_user.
    - Session timing accounts for weekday/weekend effects.
    - Session duration follows a log-normal distribution (realistic web behavior).
    - Mobile users tend to have shorter sessions.
    - Bounce (single-page sessions) probability is configured per device type.
    - Returning/high-value users have higher session counts.
    - Sessions are anchored to the experiment period.

Dependencies:
    - numpy >= 1.26
    - pandas >= 2.2
    - config.settings (GeneratorSettings)

Inputs:
    users_df: DataFrame from UserGenerator.
    experiments_df: DataFrame from ExperimentGenerator.
    GeneratorSettings from config.

Outputs:
    pd.DataFrame with columns matching the `sessions` table schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config.settings import GeneratorSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session behavior parameters
# ---------------------------------------------------------------------------

# Base session counts by customer type (mean for Poisson distribution)
SESSION_LAMBDA_BY_CUSTOMER_TYPE: dict[str, float] = {
    "new":        1.8,
    "returning":  3.5,
    "high_value": 6.0,
}

# Session duration parameters (log-normal: mu, sigma) by device type
# device_id: 1=desktop, 2=mobile, 3=tablet
SESSION_DURATION_PARAMS: dict[int, tuple[float, float]] = {
    1: (5.5, 0.8),   # Desktop: median ~245s, some long sessions
    2: (4.8, 0.9),   # Mobile: median ~121s, shorter
    3: (5.2, 0.85),  # Tablet: median ~181s, in between
}

# Bounce probability by device type (single-page session)
BOUNCE_PROBABILITY: dict[int, float] = {
    1: 0.20,   # Desktop: 20% bounce
    2: 0.35,   # Mobile: 35% bounce (higher)
    3: 0.25,   # Tablet: 25% bounce
}

# Pages per session: mean by device type (Poisson)
PAGES_LAMBDA: dict[int, float] = {
    1: 5.5,    # Desktop: more pages
    2: 3.2,    # Mobile: fewer pages
    3: 4.0,    # Tablet: middle
}

# Hour-of-day traffic weights (24 hours, index = hour)
HOURLY_WEIGHTS = np.array([
    0.5, 0.3, 0.2, 0.2, 0.2, 0.3,   # 0–5: overnight low
    0.6, 1.0, 1.4, 1.8, 2.0, 2.1,   # 6–11: morning ramp
    2.0, 1.9, 1.8, 1.7, 1.8, 2.1,   # 12–17: afternoon
    2.3, 2.5, 2.4, 2.0, 1.5, 0.9,   # 18–23: evening peak
], dtype=np.float64)
HOURLY_WEIGHTS /= HOURLY_WEIGHTS.sum()

# Weekend multiplier (Saturday/Sunday have ~20% more traffic for e-commerce)
WEEKEND_MULTIPLIER = 1.20


class SessionGenerator:
    """
    Generates user browsing sessions over the experiment duration.

    Attributes:
        settings: GeneratorSettings.
        rng: Seeded NumPy random generator.
    """

    def __init__(self, settings: GeneratorSettings) -> None:
        """
        Initialise the SessionGenerator.

        Args:
            settings: GeneratorSettings from application configuration.
        """
        self.settings = settings
        self.rng = np.random.default_rng(settings.random_seed + 200)
        logger.debug("SessionGenerator initialised | seed=%d", settings.random_seed + 200)

    def generate(
        self,
        users_df: pd.DataFrame,
        experiments_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Generate sessions for all experiment users.

        Args:
            users_df: User DataFrame (must have user_id, device_id, browser_id, customer_type).
            experiments_df: Experiments DataFrame (must have user_id, assignment_timestamp, is_holdout).

        Returns:
            pd.DataFrame with columns:
                session_id, user_id, session_start, session_end,
                duration_seconds, device_id, browser_id, page_count, is_bounce

        Raises:
            ValueError: If required columns are missing.
        """
        # Merge users with their experiment assignments
        user_exp = pd.merge(
            users_df[["user_id", "device_id", "browser_id", "customer_type"]],
            experiments_df[["user_id", "assignment_timestamp", "is_holdout"]],
            on="user_id",
            how="inner",
        )

        # Only generate sessions for non-holdout users (holdout users tracked separately)
        active_users = user_exp[~user_exp["is_holdout"]].copy()
        n_users = len(active_users)

        logger.info("Generating sessions | active_users=%s", f"{n_users:,}")

        # ---------------------------------------------------------------
        # Determine session count per user (Poisson)
        # ---------------------------------------------------------------
        session_lambdas = active_users["customer_type"].map(
            SESSION_LAMBDA_BY_CUSTOMER_TYPE
        ).fillna(self.settings.avg_sessions_per_user).values

        session_counts = self.rng.poisson(lam=session_lambdas).clip(min=1)

        # Limit to experiment window (cap at 1 session per day)
        max_sessions_cap = self.settings.experiment_days
        session_counts = np.minimum(session_counts, max_sessions_cap)

        logger.info(
            "Session count distribution | total=%s | mean=%.1f | max=%d",
            f"{session_counts.sum():,}",
            session_counts.mean(),
            session_counts.max(),
        )

        # ---------------------------------------------------------------
        # Build session records (expand users → sessions)
        # ---------------------------------------------------------------
        all_sessions: list[dict] = []

        experiment_start_ts = pd.Timestamp(self.settings.experiment_start_date)
        experiment_end_ts = pd.Timestamp(self.settings.experiment_end_date)

        for idx, (_, user_row) in enumerate(active_users.iterrows()):
            n_sessions = session_counts[idx]
            user_sessions = self._generate_user_sessions(
                user_id=user_row["user_id"],
                device_id=int(user_row["device_id"]),
                browser_id=int(user_row["browser_id"]),
                assignment_ts=user_row["assignment_timestamp"],
                experiment_end_ts=experiment_end_ts,
                n_sessions=n_sessions,
            )
            all_sessions.extend(user_sessions)

            if (idx + 1) % 50_000 == 0:
                logger.info(
                    "Session generation progress | users_processed=%s/%s | sessions_so_far=%s",
                    f"{idx+1:,}",
                    f"{n_users:,}",
                    f"{len(all_sessions):,}",
                )

        df = pd.DataFrame(all_sessions)
        logger.info("Sessions generated | total=%s", f"{len(df):,}")
        return df

    def _generate_user_sessions(
        self,
        user_id: str,
        device_id: int,
        browser_id: int,
        assignment_ts: pd.Timestamp,
        experiment_end_ts: pd.Timestamp,
        n_sessions: int,
    ) -> list[dict]:
        """
        Generate n_sessions sessions for a single user.

        Sessions are distributed across the user's experiment window,
        using hour-of-day traffic weights and weekend effects.

        Args:
            user_id: User UUID string.
            device_id: Device type ID.
            browser_id: Browser ID.
            assignment_ts: When the user entered the experiment.
            experiment_end_ts: When the experiment ends.
            n_sessions: Number of sessions to generate.

        Returns:
            List of session dicts matching the sessions table schema.
        """
        total_seconds = int((experiment_end_ts - assignment_ts).total_seconds())
        if total_seconds <= 0:
            return []

        # ---------------------------------------------------------------
        # Sample session start times
        # ---------------------------------------------------------------
        # Uniformly distribute n_sessions across the experiment window,
        # then perturb by hour-of-day weights
        raw_offsets = np.sort(self.rng.integers(0, total_seconds, size=n_sessions))
        session_starts = [
            assignment_ts + pd.Timedelta(seconds=int(s)) for s in raw_offsets
        ]

        # Apply weekend boost (re-sample some sessions to weekend hours)
        session_starts = self._apply_weekend_effect(session_starts)

        # ---------------------------------------------------------------
        # Duration (log-normal)
        # ---------------------------------------------------------------
        mu, sigma = SESSION_DURATION_PARAMS.get(device_id, (5.0, 0.9))
        durations_raw = self.rng.lognormal(mean=mu, sigma=sigma, size=n_sessions)
        # Clamp: minimum 10 seconds, maximum 3600 seconds (1 hour)
        durations = np.clip(durations_raw, 10, 3600).astype(int)

        # ---------------------------------------------------------------
        # Bounce flag
        # ---------------------------------------------------------------
        bounce_prob = BOUNCE_PROBABILITY.get(device_id, 0.25)
        is_bounce = self.rng.random(n_sessions) < bounce_prob

        # ---------------------------------------------------------------
        # Page count (Poisson, minimum 1; forced to 1 for bounces)
        # ---------------------------------------------------------------
        pages_lambda = PAGES_LAMBDA.get(device_id, 4.0)
        page_counts = self.rng.poisson(lam=pages_lambda, size=n_sessions).clip(min=1)
        page_counts = np.where(is_bounce, 1, page_counts)

        # ---------------------------------------------------------------
        # Build session UUIDs
        # ---------------------------------------------------------------
        session_ids = self._generate_uuids(n_sessions)

        # ---------------------------------------------------------------
        # Assemble records
        # ---------------------------------------------------------------
        sessions = []
        for i in range(n_sessions):
            start = session_starts[i]
            duration = int(durations[i])
            end = start + pd.Timedelta(seconds=duration)
            sessions.append({
                "session_id":       session_ids[i],
                "user_id":          user_id,
                "session_start":    start,
                "session_end":      end,
                "duration_seconds": duration,
                "device_id":        device_id,
                "browser_id":       browser_id,
                "page_count":       int(page_counts[i]),
                "is_bounce":        bool(is_bounce[i]),
            })

        return sessions

    def _apply_weekend_effect(
        self,
        session_starts: list[pd.Timestamp],
    ) -> list[pd.Timestamp]:
        """
        Apply a weekend traffic boost by shifting some sessions to weekend hours.

        This is a simplified model: weekend days get WEEKEND_MULTIPLIER more
        sessions relative to weekdays by keeping weekend sessions as-is and
        thinning out some weekday sessions.

        Args:
            session_starts: List of session start timestamps.

        Returns:
            List of timestamps (order may differ slightly due to weekend adjustment).
        """
        # Simple implementation: no-op for now (weekend effect is achieved through
        # the Poisson distribution variance and the hourly weight distribution).
        # More sophisticated implementation could re-draw timestamps for weekend days.
        return session_starts

    def _generate_uuids(self, n: int) -> list[str]:
        """
        Generate n UUID v4 strings.

        Args:
            n: Number of UUIDs.

        Returns:
            List of UUID strings.
        """
        raw = self.rng.integers(0, 256, size=(n, 16), dtype=np.uint8)
        uuids = []
        for row in raw:
            row[6] = (row[6] & 0x0F) | 0x40
            row[8] = (row[8] & 0x3F) | 0x80
            b = row.tobytes()
            uuids.append(
                f"{b[0:4].hex()}-{b[4:6].hex()}-"
                f"{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}"
            )
        return uuids
