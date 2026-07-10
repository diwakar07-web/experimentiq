"""
ExperimentIQ Analytics Package
================================
Provides DatasetBuilder, MetricsEngine, FunnelAnalyzer, and SegmentAnalyzer
for computing and assembling all business metrics from PostgreSQL analytical views.
"""

from src.analytics.dataset_builder import DatasetBuilder
from src.analytics.metrics_engine import MetricsEngine, ExperimentMetrics
from src.analytics.funnel_analyzer import FunnelAnalyzer, FunnelStep
from src.analytics.segment_analyzer import SegmentAnalyzer

__all__ = [
    "DatasetBuilder",
    "MetricsEngine",
    "ExperimentMetrics",
    "FunnelAnalyzer",
    "FunnelStep",
    "SegmentAnalyzer",
]
