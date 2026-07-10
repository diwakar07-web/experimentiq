"""
ExperimentIQ — Dataset Exporter

Purpose:
    Exports processed analytical datasets as CSV files for Power BI consumption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict
import pandas as pd

from config.settings import Settings
from src.reporting.report_builder import ExperimentReport

logger = logging.getLogger(__name__)

class DatasetExporter:
    """Exports structured analytical datasets to CSV for external consumption."""
    
    def __init__(self, export_path: Path, settings: Settings) -> None:
        self.export_path = export_path
        self.settings = settings
        
        # Ensure export directory exists
        self.export_path.mkdir(parents=True, exist_ok=True)
        logger.debug("DatasetExporter initialised | export_path=%s", export_path)

    def export_all(self, report: ExperimentReport, dataset: Dict[str, pd.DataFrame]) -> Dict[str, Path]:
        """Export all datasets and statistical results to CSV files."""
        exported_files = {}
        
        # Export base dataframes
        for name, df in dataset.items():
            if not df.empty:
                file_path = self.export_dataframe(df, f"{name}.csv")
                exported_files[name] = file_path
                
        # Export statistical results
        stat_path = self.export_statistical_results(report)
        exported_files["statistical_results"] = stat_path
        
        # Export recommendation
        rec_path = self.export_recommendation(report)
        exported_files["recommendation"] = rec_path
        
        logger.info("Successfully exported %d files to %s", len(exported_files), self.export_path)
        return exported_files

    def export_dataframe(self, df: pd.DataFrame, filename: str) -> Path:
        """Export a single DataFrame to a CSV file."""
        file_path = self.export_path / filename
        try:
            df.to_csv(file_path, index=False)
            logger.debug("Exported %d rows to %s", len(df), file_path)
            return file_path
        except Exception as e:
            logger.error("Failed to export dataframe to %s: %s", file_path, e)
            raise

    def export_statistical_results(self, report: ExperimentReport) -> Path:
        """Extract statistical results into a flattened CSV format."""
        stat_data = {
            "experiment_name": report.experiment_name,
            "generated_at": report.generated_at.isoformat(),
            "p_value": report.z_test.p_value,
            "z_score": report.z_test.z_score,
            "is_significant": report.z_test.is_significant,
            "absolute_lift": report.z_test.absolute_lift,
            "relative_lift_pct": report.z_test.relative_lift_pct,
            "ci_lower": report.confidence_interval.lower,
            "ci_upper": report.confidence_interval.upper,
            "achieved_power": report.power_analysis.achieved_power,
            "cohens_h": report.effect_size.cohens_h,
            "srm_detected": report.srm_result.srm_detected,
            "srm_p_value": report.srm_result.p_value
        }
        
        df = pd.DataFrame([stat_data])
        return self.export_dataframe(df, "statistical_results.csv")

    def export_recommendation(self, report: ExperimentReport) -> Path:
        """Export the final business recommendation."""
        rec_data = {
            "experiment_name": report.experiment_name,
            "generated_at": report.generated_at.isoformat(),
            "recommendation": report.recommendation.recommendation.value,
            "decision": report.recommendation.decision,
            "confidence": report.recommendation.confidence,
            "summary": report.recommendation.summary
        }
        
        df = pd.DataFrame([rec_data])
        return self.export_dataframe(df, "recommendation.csv")
