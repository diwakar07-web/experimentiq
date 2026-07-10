"""
ExperimentIQ — Order Generator

Purpose:
    Generates purchase order records from purchase events. Produces a
    DataFrame matching the `orders` table schema.

    Orders are derived from purchase events — every successful purchase
    event generates exactly one order. This maintains referential integrity
    between events and orders.

Design:
    - One order per purchase event (deterministic link via event_id).
    - Order value matches the revenue in the corresponding purchase event.
    - Payment method is sampled from a realistic distribution.
    - A fraction of orders are marked as refunded (simulated post-purchase).
    - Payment status reflects the event type (purchase → completed, etc.).

Dependencies:
    - numpy >= 1.26
    - pandas >= 2.2
    - config.settings (GeneratorSettings)

Inputs:
    events_df: DataFrame from EventGenerator.
    sessions_df: DataFrame from SessionGenerator.
    GeneratorSettings.

Outputs:
    pd.DataFrame with columns matching the `orders` table schema.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.settings import GeneratorSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# event_type_id for purchase (from schema.sql seed)
PURCHASE_EVENT_TYPE_ID = 9

# Payment method distribution
PAYMENT_METHOD_WEIGHTS: dict[str, float] = {
    "credit_card":    0.40,
    "debit_card":     0.20,
    "paypal":         0.18,
    "apple_pay":      0.12,
    "google_pay":     0.07,
    "bank_transfer":  0.03,
}

# Refund rate: fraction of completed orders that are subsequently refunded
REFUND_RATE = 0.04

# Minimum order value (sanity check / floor)
MIN_ORDER_VALUE = 1.00


class OrderGenerator:
    """
    Generates order records from purchase events.

    Attributes:
        settings: GeneratorSettings.
        rng: Seeded NumPy random generator.
    """

    def __init__(self, settings: GeneratorSettings) -> None:
        """
        Initialise the OrderGenerator.

        Args:
            settings: GeneratorSettings from application configuration.
        """
        self.settings = settings
        self.rng = np.random.default_rng(settings.random_seed + 400)
        logger.debug("OrderGenerator initialised | seed=%d", settings.random_seed + 400)

    def generate(
        self,
        events_df: pd.DataFrame,
        sessions_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Generate orders from purchase events.

        Args:
            events_df: Events DataFrame. Must contain:
                       event_id, session_id, user_id, event_type_id,
                       event_timestamp, revenue.
            sessions_df: Sessions DataFrame. Must contain:
                         session_id (for FK linkage).

        Returns:
            pd.DataFrame with columns:
                order_id, user_id, session_id, event_id, order_timestamp,
                order_value, payment_method, is_refund, payment_status

        Raises:
            ValueError: If no purchase events are found.
        """
        required_event_cols = [
            "event_id", "session_id", "user_id", "event_type_id",
            "event_timestamp", "revenue",
        ]
        for col in required_event_cols:
            if col not in events_df.columns:
                raise ValueError(f"events_df missing column: {col}")

        # Extract only successful purchase events
        purchase_events = events_df[
            events_df["event_type_id"] == PURCHASE_EVENT_TYPE_ID
        ].copy()

        if purchase_events.empty:
            logger.warning(
                "No purchase events found in events_df — no orders will be generated"
            )
            return pd.DataFrame(columns=[
                "order_id", "user_id", "session_id", "event_id",
                "order_timestamp", "order_value", "payment_method",
                "is_refund", "payment_status",
            ])

        n_orders = len(purchase_events)
        logger.info("Generating orders | purchase_events=%s", f"{n_orders:,}")

        # ---------------------------------------------------------------
        # Order values — use revenue from purchase event
        # Floor at minimum order value
        # ---------------------------------------------------------------
        order_values = purchase_events["revenue"].fillna(50.0).clip(lower=MIN_ORDER_VALUE).values

        # ---------------------------------------------------------------
        # Payment methods
        # ---------------------------------------------------------------
        methods = list(PAYMENT_METHOD_WEIGHTS.keys())
        method_probs = np.array(list(PAYMENT_METHOD_WEIGHTS.values()), dtype=np.float64)
        method_probs /= method_probs.sum()
        payment_methods = self.rng.choice(methods, size=n_orders, p=method_probs)

        # ---------------------------------------------------------------
        # Refund flags — applied to a fraction of completed orders
        # ---------------------------------------------------------------
        is_refund = self.rng.random(n_orders) < REFUND_RATE

        # ---------------------------------------------------------------
        # Payment status — all purchase events are 'completed'
        # (failed payments become purchase_failed events, not orders)
        # ---------------------------------------------------------------
        payment_status = np.where(is_refund, "refunded", "completed")

        # ---------------------------------------------------------------
        # Order timestamps — same as the purchase event timestamp
        # ---------------------------------------------------------------
        order_timestamps = purchase_events["event_timestamp"].values

        # ---------------------------------------------------------------
        # Generate order UUIDs
        # ---------------------------------------------------------------
        order_ids = self._generate_uuids(n_orders)

        # ---------------------------------------------------------------
        # Assemble DataFrame
        # ---------------------------------------------------------------
        df = pd.DataFrame({
            "order_id":        order_ids,
            "user_id":         purchase_events["user_id"].values,
            "session_id":      purchase_events["session_id"].values,
            "event_id":        purchase_events["event_id"].values,
            "order_timestamp": order_timestamps,
            "order_value":     order_values.round(2),
            "payment_method":  payment_methods,
            "is_refund":       is_refund,
            "payment_status":  payment_status,
        })

        refund_count = df["is_refund"].sum()
        logger.info(
            "Orders generated | total=%s | refunded=%s (%.1f%%) | "
            "total_revenue=$%s | avg_order_value=$%.2f",
            f"{len(df):,}",
            f"{refund_count:,}",
            100 * refund_count / len(df) if len(df) > 0 else 0,
            f"{df['order_value'].sum():,.0f}",
            df["order_value"].mean(),
        )
        return df

    def _generate_uuids(self, n: int) -> np.ndarray:
        """
        Generate n UUID v4 strings.

        Args:
            n: Number of UUIDs.

        Returns:
            NumPy array of UUID strings.
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
        return np.array(uuids, dtype=str)
