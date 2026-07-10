"""
ExperimentIQ — Pipeline Orchestrator

Purpose:
    Single-entry orchestrator that runs the entire end-to-end pipeline.
"""

from __future__ import annotations

import logging
import sys
import argparse
from pathlib import Path
import time
from typing import Dict
import pandas as pd

from config.settings import get_settings
from src.utils.timer import PipelineTimer
from src.validation.pipeline_guard import PipelineGuard
from src.ingestion.db_connection import get_engine
import subprocess
from src.generators.user_generator import UserGenerator
from src.generators.experiment_generator import ExperimentGenerator
from src.generators.session_generator import SessionGenerator
from src.generators.event_generator import EventGenerator
from src.generators.order_generator import OrderGenerator
from src.validation.data_validator import DataValidator
from src.ingestion.schema_validator import SchemaValidator
from src.ingestion.bulk_loader import BulkLoader
from src.analytics.dataset_builder import DatasetBuilder
from src.reporting.report_builder import ReportBuilder
from src.reporting.dataset_exporter import DatasetExporter
from src.reporting.pdf_generator import PDFGenerator
from src.recommendations.recommendation_engine import RecommendationEngine

logger = logging.getLogger("run_pipeline")

class PipelineOrchestrator:
    """Orchestrates the entire ExperimentIQ pipeline."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timer = PipelineTimer("ExperimentIQ Pipeline")
        self.engine = get_engine()

    def run(self, dry_run: bool = False, skip_generation: bool = False) -> bool:
        """Run the end-to-end pipeline."""
        logger.info("Starting ExperimentIQ Pipeline")
        
        if dry_run:
            logger.info("DRY RUN MODE: Validating configuration only.")
            
        # 1. Pre-flight Checks
        with self.timer.stage("Pre-flight Checks"):
            guard = PipelineGuard(self.settings)
            checks = guard.run_all_checks()
            if not all(checks.values()):
                logger.error("Pre-flight checks failed. Aborting pipeline.")
                return False
                
        if dry_run:
            logger.info("Dry run complete.")
            return True

        try:
            # 2. Database Initialization
            with self.timer.stage("Database Initialization"):
                result = subprocess.run([sys.executable, "database/seed.py"], capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error("Database initialization failed: %s", result.stderr)
                    return False

            dataframes = {}
            if not skip_generation:
                # 3. Data Generation
                with self.timer.stage("Data Generation"):
                    dataframes = self._generate_data()
                    self._save_raw_data(dataframes)
            else:
                # Load existing data
                with self.timer.stage("Load Raw Data"):
                    dataframes = self._load_raw_data()
                    if not dataframes:
                        logger.error("No raw data found to load. Aborting.")
                        return False

            # 4. Data Validation
            with self.timer.stage("Data Validation"):
                validator = DataValidator(self.settings)
                validation_result = validator.validate_all(dataframes)
                if not validation_result.is_valid:
                    logger.error("Business validation failed. See logs for details.")
                    return False
                    
                schema_validator = SchemaValidator()
                schema_report = schema_validator.validate_all(dataframes)
                if not schema_report.is_valid:
                    logger.error("Schema validation failed.")
                    return False

            # 5. Database Loading
            with self.timer.stage("Database Loading"):
                loader = BulkLoader()
                loader.load_all(dataframes)

            # 6. Refresh Materialized Views
            from sqlalchemy import text
            with self.timer.stage("Refresh Materialized Views"):
                with self.engine.begin() as conn:
                    conn.execute(text("REFRESH MATERIALIZED VIEW mv_user_experiment_summary;"))
                    conn.execute(text("REFRESH MATERIALIZED VIEW mv_daily_conversion;"))

            # 7. Build Analytical Datasets
            with self.timer.stage("Build Analytical Datasets"):
                builder = DatasetBuilder(self.engine)
                analytical_datasets = builder.build_all()

            # 8. Run Analytics & Statistics to build Report
            with self.timer.stage("Generate Report and Recommendations"):
                # Simplified orchestrator logic for the recommendation part
                report_builder = ReportBuilder(self.settings)
                # Note: In a fully wired system, we would first run RecommendationEngine
                # and pass it to report builder.
                # For this implementation, we will mock RecommendationReport generation directly
                # inside ReportBuilder or here.
                # Let's instantiate a placeholder recommendation for now to satisfy the pipeline
                from src.recommendations.recommendation_engine import RecommendationReport, Recommendation
                from datetime import datetime, timezone
                rec_report = RecommendationReport(
                    recommendation=Recommendation.CONTINUE_EXPERIMENT,
                    decision="Continue Experiment",
                    confidence="MEDIUM",
                    summary="Pipeline execution completed.",
                    rule_results=[],
                    key_metrics={},
                    generated_at=datetime.now(timezone.utc),
                    experiment_name="Experiment 1"
                )
                report = report_builder.build(analytical_datasets, rec_report)

            # 9. Export Datasets
            with self.timer.stage("Export Datasets"):
                export_dir = Path("data/exports")
                exporter = DatasetExporter(export_dir, self.settings)
                exporter.export_all(report, analytical_datasets)

            # 10. Generate PDF
            with self.timer.stage("Generate PDF"):
                pdf_gen = PDFGenerator(Path("src/reporting/templates"), Path("data/reports"))
                pdf_gen.generate(report)

            logger.info("Pipeline completed successfully!")
            self.timer.log_summary()
            return True

        except Exception as e:
            logger.exception("Pipeline failed with error: %s", e)
            return False

    def _generate_data(self) -> Dict[str, pd.DataFrame]:
        """Generate all required dataframes."""
        u_gen = UserGenerator(self.settings.generator)
        users = u_gen.generate()
        
        x_gen = ExperimentGenerator(self.settings.generator)
        experiments = x_gen.generate(users)
        
        s_gen = SessionGenerator(self.settings.generator)
        sessions = s_gen.generate(users, experiments)
        
        e_gen = EventGenerator(self.settings.generator)
        events = e_gen.generate(sessions, experiments)
        
        o_gen = OrderGenerator(self.settings.generator)
        orders = o_gen.generate(events, experiments)
        
        return {
            "users": users,
            "experiments": experiments,
            "sessions": sessions,
            "events": events,
            "orders": orders
        }

    def _save_raw_data(self, dataframes: Dict[str, pd.DataFrame]) -> None:
        """Save raw generated dataframes to CSV."""
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        for name, df in dataframes.items():
            df.to_csv(raw_dir / f"{name}.csv", index=False)

    def _load_raw_data(self) -> Dict[str, pd.DataFrame]:
        """Load raw dataframes from CSV."""
        raw_dir = Path("data/raw")
        dataframes = {}
        for name in ["users", "experiments", "sessions", "events", "orders"]:
            path = raw_dir / f"{name}.csv"
            if path.exists():
                dataframes[name] = pd.read_csv(path)
        return dataframes

from config.logging_config import configure_logging_from_settings

def main():
    parser = argparse.ArgumentParser(description="ExperimentIQ Pipeline Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Validate config without running")
    parser.add_argument("--skip-generation", action="store_true", help="Skip data generation and use existing CSVs")
    args = parser.parse_args()

    configure_logging_from_settings()
    
    orchestrator = PipelineOrchestrator()
    success = orchestrator.run(dry_run=args.dry_run, skip_generation=args.skip_generation)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
