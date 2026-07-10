"""
ExperimentIQ — Event Generator

Purpose:
    Generates individual user events within each session, simulating the
    user journey through the e-commerce funnel. Produces a DataFrame matching
    the `events` table schema.

Design:
    - Events follow the funnel: page_view → product_view → add_to_cart →
      checkout_start → checkout_payment → purchase.
    - Each step has a configured drop-off probability.
    - Variant users have a higher checkout→purchase conversion rate.
    - Non-funnel events (scroll, click, search) are interspersed randomly.
    - Revenue field is set only for purchase events (log-normal distribution).
    - Payment failure events are generated for a fraction of purchase attempts.
    - Refund events are simulated for a fraction of completed purchases.
    - Each event has a sequential timestamp within the session window.

Dependencies:
    - numpy >= 1.26
    - pandas >= 2.2
    - config.settings (GeneratorSettings)

Inputs:
    sessions_df: DataFrame from SessionGenerator.
    experiments_df: DataFrame from ExperimentGenerator.
    GeneratorSettings.

Outputs:
    pd.DataFrame with columns matching the `events` table schema.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import GeneratorSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type IDs (must match schema.sql seed data ORDER)
# ---------------------------------------------------------------------------
EVENT_IDS = {
    "page_view":           1,
    "product_view":        2,
    "search":              3,
    "add_to_cart":         4,
    "cart_view":           5,
    "checkout_start":      6,
    "checkout_address":    7,
    "checkout_payment":    8,
    "purchase":            9,
    "purchase_failed":     10,
    "refund":              11,
    "session_start":       12,
    "session_end":         13,
    "scroll":              14,
    "click":               15,
    "wishlist_add":        16,
    "coupon_applied":      17,
    "checkout_abandoned":  18,
}

# ---------------------------------------------------------------------------
# Funnel drop-off rates (per step, given user reached previous step)
# Base rates for CONTROL group. Variant modifies at checkout→purchase.
# ---------------------------------------------------------------------------

# Probability of reaching each step given the session started
FUNNEL_RATES_CONTROL = {
    "product_view":     0.65,   # 65% of sessions view a product
    "add_to_cart":      0.30,   # 30% of product viewers add to cart
    "checkout_start":   0.55,   # 55% of cart viewers start checkout
    "checkout_payment": 0.75,   # 75% of checkout starters reach payment
    "purchase":         0.55,   # 55% of payment page visitors purchase
}

# Revenue distribution parameters (log-normal): mean and std of log(revenue)
REVENUE_LOG_MEAN = 4.0    # ~ $54 USD median order value
REVENUE_LOG_STD  = 0.7

# Payment failure rate
PAYMENT_FAILURE_RATE = 0.08   # 8% of purchase attempts fail

# Refund rate (applied after successful purchases)
REFUND_RATE = 0.04            # 4% of completed purchases are refunded

# Non-funnel engagement events per funnel step
ENGAGEMENT_EVENTS_MEAN = 2.0  # Average engagement events before each funnel step


class EventGenerator:
    """
    Generates events for all sessions in the experiment.

    Attributes:
        settings: GeneratorSettings.
        rng: Seeded NumPy random generator.
        variant_conversion_boost: Uplift on checkout→purchase for variant users.
    """

    def __init__(self, settings: GeneratorSettings) -> None:
        """
        Initialise the EventGenerator.

        Args:
            settings: GeneratorSettings containing conversion rates and uplift.
        """
        self.settings = settings
        self.rng = np.random.default_rng(settings.random_seed + 300)

        # The variant boost is applied at the final funnel step (purchase)
        self.variant_conversion_boost = settings.variant_uplift
        logger.debug(
            "EventGenerator initialised | seed=%d | variant_uplift=%.3f",
            settings.random_seed + 300,
            settings.variant_uplift,
        )

    def generate(
        self,
        sessions_df: pd.DataFrame,
        experiments_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Generate all events across all sessions.

        Args:
            sessions_df: Sessions DataFrame (must include session_id, user_id,
                         session_start, session_end, device_id, is_bounce).
            experiments_df: Experiments DataFrame (must include user_id, variant,
                            experiment_id, is_holdout).

        Returns:
            pd.DataFrame with columns:
                event_id, session_id, user_id, experiment_id,
                event_type_id, event_timestamp, page_url, revenue, is_mobile

        Raises:
            ValueError: If required columns are missing.
        """
        required_session_cols = ["session_id", "user_id", "session_start", "session_end",
                                  "device_id", "is_bounce"]
        required_exp_cols = ["user_id", "variant", "experiment_id", "is_holdout"]

        for col in required_session_cols:
            if col not in sessions_df.columns:
                raise ValueError(f"sessions_df missing column: {col}")
        for col in required_exp_cols:
            if col not in experiments_df.columns:
                raise ValueError(f"experiments_df missing column: {col}")

        # Join sessions with experiment info
        exp_info = experiments_df[experiments_df["is_holdout"] == False][
            ["user_id", "variant", "experiment_id"]
        ].copy()

        sessions_with_exp = pd.merge(
            sessions_df,
            exp_info,
            on="user_id",
            how="inner",
        )

        n_sessions = len(sessions_with_exp)
        logger.info("Generating events | sessions=%s", f"{n_sessions:,}")

        all_events: list[dict] = []

        for idx, (_, session) in enumerate(sessions_with_exp.iterrows()):
            session_events = self._generate_session_events(session)
            all_events.extend(session_events)

            if (idx + 1) % 100_000 == 0:
                logger.info(
                    "Event generation progress | sessions=%s/%s | events_so_far=%s",
                    f"{idx+1:,}",
                    f"{n_sessions:,}",
                    f"{len(all_events):,}",
                )

        if not all_events:
            logger.warning("No events generated — check session and experiment data")
            return pd.DataFrame(columns=[
                "event_id", "session_id", "user_id", "experiment_id",
                "event_type_id", "event_timestamp", "page_url", "revenue", "is_mobile"
            ])

        df = pd.DataFrame(all_events)
        logger.info(
            "Events generated | total=%s | purchase_events=%s",
            f"{len(df):,}",
            f"{(df['event_type_id'] == EVENT_IDS['purchase']).sum():,}",
        )
        return df

    def _generate_session_events(self, session: pd.Series) -> list[dict]:
        """
        Generate all events for a single session following the funnel model.

        Args:
            session: A row from the sessions_with_exp DataFrame.

        Returns:
            List of event dicts.
        """
        events: list[dict] = []
        session_id = session["session_id"]
        user_id = session["user_id"]
        experiment_id = session["experiment_id"]
        variant = session["variant"]
        is_bounce = bool(session["is_bounce"])
        device_id = int(session["device_id"])
        is_mobile = device_id == 2

        session_start = pd.Timestamp(session["session_start"])
        session_end = pd.Timestamp(session["session_end"])
        session_duration = (session_end - session_start).total_seconds()

        if session_duration <= 0:
            return events

        # Track current position in the session timeline (seconds from start)
        time_cursor = 0.0

        # Compute variant-adjusted funnel rates
        funnel_rates = self._get_funnel_rates(variant)

        # ---------------------------------------------------------------
        # Step 1: page_view (every session starts with this)
        # ---------------------------------------------------------------
        events.append(self._make_event(
            session_id=session_id, user_id=user_id, experiment_id=experiment_id,
            event_type_id=EVENT_IDS["page_view"],
            session_start=session_start, time_offset=time_cursor,
            page_url="/landing", is_mobile=is_mobile, session_duration=session_duration,
        ))
        time_cursor += self._random_time_gap(session_duration, 10, 30)

        if is_bounce:
            return events  # Bounce: user leaves after landing page

        # ---------------------------------------------------------------
        # Add engagement events (scroll, click)
        # ---------------------------------------------------------------
        events.extend(self._generate_engagement_events(
            session_id, user_id, experiment_id, session_start,
            time_cursor, session_duration, is_mobile,
        ))
        time_cursor += self._random_time_gap(session_duration, 15, 60)

        # ---------------------------------------------------------------
        # Step 2: product_view
        # ---------------------------------------------------------------
        if not self._proceed(funnel_rates["product_view"]):
            return events

        events.append(self._make_event(
            session_id=session_id, user_id=user_id, experiment_id=experiment_id,
            event_type_id=EVENT_IDS["product_view"],
            session_start=session_start, time_offset=time_cursor,
            page_url="/product/detail", is_mobile=is_mobile, session_duration=session_duration,
        ))
        time_cursor += self._random_time_gap(session_duration, 20, 90)

        # ---------------------------------------------------------------
        # Step 3: add_to_cart
        # ---------------------------------------------------------------
        if not self._proceed(funnel_rates["add_to_cart"]):
            return events

        events.append(self._make_event(
            session_id=session_id, user_id=user_id, experiment_id=experiment_id,
            event_type_id=EVENT_IDS["add_to_cart"],
            session_start=session_start, time_offset=time_cursor,
            page_url="/cart", is_mobile=is_mobile, session_duration=session_duration,
        ))
        time_cursor += self._random_time_gap(session_duration, 10, 30)

        # ---------------------------------------------------------------
        # Step 4: checkout_start
        # ---------------------------------------------------------------
        if not self._proceed(funnel_rates["checkout_start"]):
            # Checkout abandoned
            events.append(self._make_event(
                session_id=session_id, user_id=user_id, experiment_id=experiment_id,
                event_type_id=EVENT_IDS["checkout_abandoned"],
                session_start=session_start, time_offset=time_cursor,
                page_url="/cart", is_mobile=is_mobile, session_duration=session_duration,
            ))
            return events

        events.append(self._make_event(
            session_id=session_id, user_id=user_id, experiment_id=experiment_id,
            event_type_id=EVENT_IDS["checkout_start"],
            session_start=session_start, time_offset=time_cursor,
            page_url="/checkout", is_mobile=is_mobile, session_duration=session_duration,
        ))
        time_cursor += self._random_time_gap(session_duration, 30, 120)

        # ---------------------------------------------------------------
        # Step 4b: checkout_payment
        # ---------------------------------------------------------------
        if not self._proceed(funnel_rates["checkout_payment"]):
            return events

        events.append(self._make_event(
            session_id=session_id, user_id=user_id, experiment_id=experiment_id,
            event_type_id=EVENT_IDS["checkout_payment"],
            session_start=session_start, time_offset=time_cursor,
            page_url="/checkout/payment", is_mobile=is_mobile, session_duration=session_duration,
        ))
        time_cursor += self._random_time_gap(session_duration, 20, 60)

        # ---------------------------------------------------------------
        # Step 5: purchase (or purchase_failed)
        # ---------------------------------------------------------------
        if not self._proceed(funnel_rates["purchase"]):
            return events

        # Determine if payment succeeds or fails
        if self.rng.random() < PAYMENT_FAILURE_RATE:
            events.append(self._make_event(
                session_id=session_id, user_id=user_id, experiment_id=experiment_id,
                event_type_id=EVENT_IDS["purchase_failed"],
                session_start=session_start, time_offset=time_cursor,
                page_url="/checkout/payment", is_mobile=is_mobile, session_duration=session_duration,
            ))
        else:
            # Successful purchase
            revenue = float(np.clip(
                self.rng.lognormal(mean=REVENUE_LOG_MEAN, sigma=REVENUE_LOG_STD),
                10.0, 5000.0,
            ))
            events.append(self._make_event(
                session_id=session_id, user_id=user_id, experiment_id=experiment_id,
                event_type_id=EVENT_IDS["purchase"],
                session_start=session_start, time_offset=time_cursor,
                page_url="/checkout/confirmation", is_mobile=is_mobile, session_duration=session_duration,
                revenue=revenue,
            ))

        return events

    def _get_funnel_rates(self, variant: str) -> dict[str, float]:
        """
        Get funnel rates, applying variant uplift at the purchase step.

        The variant's checkout redesign improves the checkout→purchase rate.
        All other funnel steps remain identical between control and variant.

        Args:
            variant: 'control' or 'variant'.

        Returns:
            Dict of step → conversion probability.
        """
        rates = dict(FUNNEL_RATES_CONTROL)
        if variant == "variant":
            # Apply relative uplift to the purchase step conversion
            base_purchase_rate = rates["purchase"]
            rates["purchase"] = min(
                base_purchase_rate * (1 + self.variant_conversion_boost),
                0.95,  # Cap at 95%
            )
        return rates

    def _proceed(self, probability: float) -> bool:
        """Return True with the given probability (Bernoulli trial)."""
        return bool(self.rng.random() < probability)

    def _random_time_gap(
        self,
        session_duration: float,
        min_seconds: float,
        max_seconds: float,
    ) -> float:
        """
        Return a random time gap bounded by the session duration.

        Args:
            session_duration: Total session length in seconds.
            min_seconds: Minimum gap.
            max_seconds: Maximum gap.

        Returns:
            Time gap in seconds.
        """
        upper_bound = max(min_seconds, min(max_seconds, session_duration * 0.3))
        if upper_bound == min_seconds:
            return float(min_seconds)
        gap = self.rng.uniform(min_seconds, upper_bound)
        return float(gap)

    def _make_event(
        self,
        session_id: str,
        user_id: str,
        experiment_id: str,
        event_type_id: int,
        session_start: pd.Timestamp,
        time_offset: float,
        page_url: str,
        is_mobile: bool,
        revenue: Optional[float] = None,
        session_duration: Optional[float] = None,
    ) -> dict:
        """
        Create a single event dict.

        Args:
            session_id: Session UUID.
            user_id: User UUID.
            experiment_id: Experiment UUID.
            event_type_id: Event type ID.
            session_start: Session start timestamp.
            time_offset: Seconds from session start.
            page_url: Page URL where event occurred.
            is_mobile: Whether device is mobile.
            revenue: Revenue amount (None for non-purchase events).
            session_duration: Used to cap time_offset.

        Returns:
            Dict matching the events table schema.
        """
        event_uuid = self._generate_single_uuid()
        if session_duration is not None:
            time_offset = min(time_offset, session_duration)
        event_ts = session_start + pd.Timedelta(seconds=time_offset)
        return {
            "event_id":        event_uuid,
            "session_id":      session_id,
            "user_id":         user_id,
            "experiment_id":   experiment_id,
            "event_type_id":   event_type_id,
            "event_timestamp": event_ts,
            "page_url":        page_url,
            "revenue":         revenue,
            "is_mobile":       is_mobile,
        }

    def _generate_engagement_events(
        self,
        session_id: str,
        user_id: str,
        experiment_id: str,
        session_start: pd.Timestamp,
        time_start: float,
        session_duration: float,
        is_mobile: bool,
    ) -> list[dict]:
        """
        Generate random engagement events (scroll, click) within a session.

        Args:
            session_id: Session UUID.
            user_id: User UUID.
            experiment_id: Experiment UUID.
            session_start: Session start timestamp.
            time_start: Current time cursor in seconds.
            session_duration: Total session duration.
            is_mobile: Whether device is mobile.

        Returns:
            List of engagement event dicts.
        """
        n_events = self.rng.poisson(lam=ENGAGEMENT_EVENTS_MEAN)
        events = []
        cursor = time_start
        for _ in range(n_events):
            gap = self.rng.uniform(2, 15)
            cursor = min(cursor + gap, session_duration * 0.9)
            event_type = EVENT_IDS["scroll"] if self.rng.random() < 0.6 else EVENT_IDS["click"]
            events.append(self._make_event(
                session_id=session_id, user_id=user_id, experiment_id=experiment_id,
                event_type_id=event_type,
                session_start=session_start, time_offset=cursor,
                page_url="/page", is_mobile=is_mobile, session_duration=session_duration,
            ))
        return events

    def _generate_single_uuid(self) -> str:
        """Generate a single UUID v4 string."""
        row = self.rng.integers(0, 256, size=16, dtype=np.uint8)
        row[6] = (row[6] & 0x0F) | 0x40
        row[8] = (row[8] & 0x3F) | 0x80
        b = row.tobytes()
        return (
            f"{b[0:4].hex()}-{b[4:6].hex()}-"
            f"{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}"
        )
