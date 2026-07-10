"""
ExperimentIQ — Experiment Assignment Generator

Purpose:
    Assigns each user to exactly one experiment variant (control or variant)
    in a randomized, persistent, balanced manner. Produces a DataFrame
    matching the `experiments` table schema.

Design:
    - 50/50 random split (configurable via settings.generator.variant_split).
    - Randomization uses a seeded RNG for reproducibility.
    - Assignment timestamps are distributed over the first 14 days of the
      experiment (simulating gradual rollout ramp-up).
    - A small configurable holdout group is excluded from analysis.
    - Each user gets exactly one assignment (UNIQUE constraint in DB).

Dependencies:
    - numpy >= 1.26
    - pandas >= 2.2
    - config.settings (GeneratorSettings)

Inputs:
    users_df: DataFrame from UserGenerator.generate().
    GeneratorSettings from config.

Outputs:
    pd.DataFrame with columns matching the `experiments` table schema.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np
import pandas as pd

from config.settings import GeneratorSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPERIMENT_NAME = "checkout_redesign_v1"
HOLDOUT_FRACTION = 0.02  # 2% holdout group


class ExperimentGenerator:
    """
    Assigns users to experiment variants and generates experiment records.

    Attributes:
        settings: GeneratorSettings controlling split ratio and seed.
        rng: Seeded NumPy random generator.
    """

    def __init__(self, settings: GeneratorSettings) -> None:
        """
        Initialise the ExperimentGenerator.

        Args:
            settings: GeneratorSettings from application configuration.
        """
        self.settings = settings
        # Use a different seed offset from UserGenerator to ensure independence
        self.rng = np.random.default_rng(settings.random_seed + 100)
        logger.debug(
            "ExperimentGenerator initialised | variant_split=%.2f | seed=%d",
            settings.variant_split,
            settings.random_seed + 100,
        )

    def generate(self, users_df: pd.DataFrame) -> pd.DataFrame:
        """
        Assign all users to experiment variants.

        Args:
            users_df: DataFrame from UserGenerator containing 'user_id'.

        Returns:
            pd.DataFrame with columns:
                experiment_id, experiment_name, variant, user_id,
                assignment_timestamp, is_holdout

        Raises:
            ValueError: If users_df is empty or missing 'user_id'.
        """
        if users_df.empty:
            raise ValueError("users_df is empty — cannot assign experiments")
        if "user_id" not in users_df.columns:
            raise ValueError("users_df must contain 'user_id' column")

        n = len(users_df)
        logger.info(
            "Generating experiment assignments | users=%s | variant_split=%.2f",
            f"{n:,}",
            self.settings.variant_split,
        )

        user_ids = users_df["user_id"].values

        # ---------------------------------------------------------------
        # Shuffle user order for unbiased random assignment
        # ---------------------------------------------------------------
        shuffle_idx = self.rng.permutation(n)
        shuffled_user_ids = user_ids[shuffle_idx]

        # ---------------------------------------------------------------
        # Holdout group assignment (first HOLDOUT_FRACTION of shuffled users)
        # ---------------------------------------------------------------
        holdout_count = max(1, int(n * HOLDOUT_FRACTION))
        is_holdout = np.zeros(n, dtype=bool)
        is_holdout[:holdout_count] = True

        # ---------------------------------------------------------------
        # Variant assignment (among non-holdout users)
        # ---------------------------------------------------------------
        non_holdout_mask = ~is_holdout
        non_holdout_count = non_holdout_mask.sum()
        variant_count = int(non_holdout_count * self.settings.variant_split)

        variants = np.full(n, "control", dtype=object)
        # Only non-holdout users get real variant assignments
        non_holdout_indices = np.where(non_holdout_mask)[0]
        variants[non_holdout_indices[:variant_count]] = "variant"
        variants[non_holdout_indices[variant_count:]] = "control"
        # Holdout users get 'control' label but is_holdout=True
        variants[is_holdout] = "control"

        # ---------------------------------------------------------------
        # Assignment timestamps — distributed over experiment ramp-up period
        # Ramp-up: first 14 days of the experiment (gradual traffic increase)
        # ---------------------------------------------------------------
        experiment_start = pd.Timestamp(self.settings.experiment_start_date)
        ramp_up_days = 14

        # Simulate ramp-up: more users assigned later in the ramp period
        # Use a beta distribution skewed toward day 7-14
        ramp_fractions = self.rng.beta(a=2.0, b=1.0, size=n)
        day_offsets_seconds = (ramp_fractions * ramp_up_days * 86400).astype(int)

        # Add random hours within each day for realism
        hour_offsets = self.rng.integers(0, 86400, size=n)
        total_seconds_offsets = day_offsets_seconds + hour_offsets

        assignment_timestamps = [
            experiment_start + pd.Timedelta(seconds=int(s))
            for s in total_seconds_offsets
        ]

        # ---------------------------------------------------------------
        # Generate experiment UUIDs
        # ---------------------------------------------------------------
        experiment_ids = self._generate_uuids(n)

        # ---------------------------------------------------------------
        # Assemble DataFrame (in original user order)
        # ---------------------------------------------------------------
        # Reverse the shuffle to maintain user_id alignment
        unshuffle_idx = np.argsort(shuffle_idx)

        df = pd.DataFrame({
            "experiment_id":        experiment_ids[unshuffle_idx],
            "experiment_name":      EXPERIMENT_NAME,
            "variant":              variants[unshuffle_idx],
            "user_id":              shuffled_user_ids[unshuffle_idx],
            "assignment_timestamp": [assignment_timestamps[i] for i in unshuffle_idx],
            "is_holdout":           is_holdout[unshuffle_idx],
        })

        # Log distribution summary
        control_n = (df["variant"] == "control").sum()
        variant_n = (df["variant"] == "variant").sum()
        holdout_n = df["is_holdout"].sum()

        logger.info(
            "Experiment assignments | control=%s (%.1f%%) | variant=%s (%.1f%%) | holdout=%s",
            f"{control_n:,}", 100 * control_n / n,
            f"{variant_n:,}", 100 * variant_n / n,
            f"{holdout_n:,}",
        )

        return df

    def _generate_uuids(self, n: int) -> np.ndarray:
        """
        Generate n UUID strings for experiment records.

        Args:
            n: Number of UUIDs needed.

        Returns:
            NumPy array of UUID strings.
        """
        raw = self.rng.integers(0, 256, size=(n, 16), dtype=np.uint8)
        uuids = []
        for row in raw:
            row[6] = (row[6] & 0x0F) | 0x40  # Version 4
            row[8] = (row[8] & 0x3F) | 0x80  # Variant
            b = row.tobytes()
            uuids.append(
                f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}"
            )
        return np.array(uuids, dtype=str)
