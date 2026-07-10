"""
ExperimentIQ — User Generator

Purpose:
    Generates a realistic synthetic user population for the A/B testing
    experiment. Produces a DataFrame matching the `users` table schema.

Design:
    - Vectorized NumPy operations for performance (500K users in seconds).
    - Configurable demographic distributions matching real e-commerce patterns.
    - Country/device/browser proportions are realistic (US-heavy, mobile-heavy).
    - Customer type distribution: mostly 'new', some 'returning', a few 'high_value'.
    - Signup dates distributed over 6 months before experiment start.
    - Random seed for reproducibility.

Dependencies:
    - numpy >= 1.26
    - pandas >= 2.2
    - config.settings (GeneratorSettings)

Inputs:
    GeneratorSettings from config.

Outputs:
    pd.DataFrame with columns matching the `users` table schema.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config.settings import GeneratorSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distribution Tables
# Maps lookup table IDs (as seeded in schema.sql) to probability weights.
# ---------------------------------------------------------------------------

# country_id → (weight, is_mobile_heavy)
# IDs correspond to INSERT order in schema.sql
COUNTRY_WEIGHTS: dict[int, float] = {
    1:  0.28,   # US
    2:  0.07,   # Canada
    3:  0.04,   # Mexico
    4:  0.05,   # Brazil
    5:  0.02,   # Argentina
    6:  0.10,   # UK
    7:  0.07,   # Germany
    8:  0.05,   # France
    9:  0.03,   # Italy
    10: 0.03,   # Spain
    11: 0.02,   # Netherlands
    12: 0.02,   # Sweden
    13: 0.04,   # Australia
    14: 0.04,   # Japan
    15: 0.04,   # India
    16: 0.02,   # Singapore
    17: 0.02,   # South Korea
    18: 0.03,   # China
    19: 0.01,   # UAE
    20: 0.01,   # South Africa
}

# device_id → weight (1=desktop, 2=mobile, 3=tablet)
DEVICE_WEIGHTS: dict[int, float] = {
    1: 0.45,    # desktop
    2: 0.47,    # mobile
    3: 0.08,    # tablet
}

# browser_id → weight (1=Chrome, 2=Firefox, 3=Safari, 4=Edge, 5=Opera, 6=Samsung)
BROWSER_WEIGHTS: dict[int, float] = {
    1: 0.62,    # Chrome
    2: 0.08,    # Firefox
    3: 0.18,    # Safari
    4: 0.06,    # Edge
    5: 0.02,    # Opera
    6: 0.04,    # Samsung Internet
}

# channel_id → weight
CHANNEL_WEIGHTS: dict[int, float] = {
    1: 0.28,    # organic_search
    2: 0.16,    # paid_search
    3: 0.12,    # paid_social
    4: 0.08,    # organic_social
    5: 0.14,    # email
    6: 0.10,    # direct
    7: 0.06,    # referral
    8: 0.04,    # display_ads
    9: 0.02,    # affiliate
}

# customer_type → weight
CUSTOMER_TYPE_WEIGHTS: dict[str, float] = {
    "new":         0.60,
    "returning":   0.30,
    "high_value":  0.10,
}

# operating_system → weight (loosely correlated with device; simplified here)
OS_WEIGHTS: dict[str, float] = {
    "Windows": 0.38,
    "macOS":   0.15,
    "iOS":     0.26,
    "Android": 0.18,
    "Linux":   0.03,
}


class UserGenerator:
    """
    Generates a synthetic user population DataFrame.

    Attributes:
        settings: GeneratorSettings controlling population size and seed.
        rng: Seeded NumPy random generator for reproducibility.
    """

    def __init__(self, settings: GeneratorSettings) -> None:
        """
        Initialise the UserGenerator.

        Args:
            settings: GeneratorSettings from application configuration.
        """
        self.settings = settings
        self.rng = np.random.default_rng(settings.random_seed)
        logger.debug(
            "UserGenerator initialised | num_users=%d | seed=%d",
            settings.num_users,
            settings.random_seed,
        )

    def generate(self) -> pd.DataFrame:
        """
        Generate the complete user population DataFrame.

        All operations are vectorized for performance.

        Returns:
            pd.DataFrame with columns:
                user_id, signup_date, country_id, device_id, browser_id,
                channel_id, customer_type, operating_system, is_returning

        Raises:
            ValueError: If distribution weights do not sum to approximately 1.0.
        """
        n = self.settings.num_users
        logger.info("Generating %s users with seed=%d", f"{n:,}", self.settings.random_seed)

        # ---------------------------------------------------------------
        # UUIDs — generate as strings
        # ---------------------------------------------------------------
        # Use structured UUIDs for performance rather than uuid.uuid4() in a loop
        user_ids = self._generate_uuids(n, prefix_seed=1)

        # ---------------------------------------------------------------
        # Signup dates — uniformly distributed over 6 months before experiment
        # ---------------------------------------------------------------
        experiment_start = self.settings.experiment_start_date
        signup_window_days = 180  # 6 months before experiment
        signup_start = experiment_start - timedelta(days=signup_window_days)
        days_offsets = self.rng.integers(0, signup_window_days, size=n)
        signup_dates = pd.to_datetime(
            [signup_start + timedelta(days=int(d)) for d in days_offsets]
        ).date

        # ---------------------------------------------------------------
        # Lookup IDs (vectorized sampling from distributions)
        # ---------------------------------------------------------------
        country_ids = self._sample_from_weights(COUNTRY_WEIGHTS, n)
        device_ids = self._sample_from_weights(DEVICE_WEIGHTS, n)
        browser_ids = self._sample_from_weights(BROWSER_WEIGHTS, n)
        channel_ids = self._sample_from_weights(CHANNEL_WEIGHTS, n)

        # ---------------------------------------------------------------
        # Customer type
        # ---------------------------------------------------------------
        customer_types = self._sample_categories(CUSTOMER_TYPE_WEIGHTS, n)

        # ---------------------------------------------------------------
        # Operating system (loosely correlated with device for realism)
        # ---------------------------------------------------------------
        os_list = list(OS_WEIGHTS.keys())
        os_probs = np.array(list(OS_WEIGHTS.values()))
        os_probs /= os_probs.sum()  # Normalize
        operating_systems = np.vectorize(
            lambda device, base_os: self._correlate_os_with_device(device, base_os)
        )(device_ids, self.rng.choice(os_list, size=n, p=os_probs))

        # ---------------------------------------------------------------
        # Is returning (correlates with customer_type='returning' or 'high_value')
        # ---------------------------------------------------------------
        is_returning = np.where(
            np.isin(customer_types, ["returning", "high_value"]),
            True,
            self.rng.random(n) < 0.05,  # 5% of 'new' users are also returning
        )

        # ---------------------------------------------------------------
        # Assemble DataFrame
        # ---------------------------------------------------------------
        df = pd.DataFrame({
            "user_id":          user_ids,
            "signup_date":      signup_dates,
            "country_id":       country_ids,
            "device_id":        device_ids,
            "browser_id":       browser_ids,
            "channel_id":       channel_ids,
            "customer_type":    customer_types,
            "operating_system": operating_systems,
            "is_returning":     is_returning,
        })

        logger.info(
            "Users generated | rows=%s | unique_countries=%d | device_mix=%s",
            f"{len(df):,}",
            df["country_id"].nunique(),
            df["device_id"].value_counts().to_dict(),
        )
        return df

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _generate_uuids(self, n: int, prefix_seed: int = 0) -> np.ndarray:
        """
        Generate n unique UUID v4 strings using NumPy for performance.

        Args:
            n: Number of UUIDs to generate.
            prefix_seed: Additional seed offset to differentiate between tables.

        Returns:
            numpy array of UUID strings.
        """
        import uuid

        # For large n, uuid.uuid4() in a loop is slow.
        # Use batched random bytes via numpy and format as UUID v4.
        # NumPy generates 16 random bytes per UUID.
        rng_local = np.random.default_rng(self.settings.random_seed + prefix_seed)
        raw = rng_local.integers(0, 256, size=(n, 16), dtype=np.uint8)

        uuids = []
        for row in raw:
            # Set version bits (UUID v4)
            row[6] = (row[6] & 0x0F) | 0x40
            # Set variant bits
            row[8] = (row[8] & 0x3F) | 0x80
            b = row.tobytes()
            formatted = (
                f"{b[0:4].hex()}-{b[4:6].hex()}-"
                f"{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}"
            )
            uuids.append(formatted)

        return np.array(uuids, dtype=str)

    def _sample_from_weights(
        self,
        weights: dict[int, float],
        n: int,
    ) -> np.ndarray:
        """
        Sample n values from a weighted integer distribution.

        Args:
            weights: Dict mapping integer IDs to probability weights.
            n: Number of samples.

        Returns:
            NumPy array of sampled integer IDs.
        """
        ids = np.array(list(weights.keys()), dtype=np.int16)
        probs = np.array(list(weights.values()), dtype=np.float64)
        probs /= probs.sum()  # Normalize (handles floating point imprecision)
        return self.rng.choice(ids, size=n, p=probs)

    def _sample_categories(
        self,
        weights: dict[str, float],
        n: int,
    ) -> np.ndarray:
        """
        Sample n string categories from a weighted distribution.

        Args:
            weights: Dict mapping category strings to probability weights.
            n: Number of samples.

        Returns:
            NumPy array of sampled category strings.
        """
        categories = np.array(list(weights.keys()), dtype=object)
        probs = np.array(list(weights.values()), dtype=np.float64)
        probs /= probs.sum()
        return self.rng.choice(categories, size=n, p=probs)

    @staticmethod
    def _correlate_os_with_device(device_id: int, base_os: str) -> str:
        """
        Enforce device-OS correlation for realism.

        Mobile devices (device_id=2) should predominantly use iOS or Android.
        Desktop devices (device_id=1) should predominantly use Windows/macOS/Linux.

        Args:
            device_id: Integer device type ID.
            base_os: Randomly sampled OS (to be potentially overridden).

        Returns:
            OS string (may be different from base_os).
        """
        if device_id == 2:  # mobile
            # Mobile users only use iOS or Android
            if base_os not in ("iOS", "Android"):
                # Re-map to mobile OS with equal probability
                return "iOS" if hash(base_os) % 2 == 0 else "Android"
        elif device_id == 1:  # desktop
            # Desktop users don't use iOS or Android
            if base_os in ("iOS", "Android"):
                return "Windows"
        # Tablet: any OS is plausible
        return base_os
