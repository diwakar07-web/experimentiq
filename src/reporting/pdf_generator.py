"""
ExperimentIQ — PDF Generator

Purpose:
    Generates a professional PDF experiment report using WeasyPrint + Jinja2.
"""

from __future__ import annotations

import logging
import base64
import io
from pathlib import Path
from typing import Dict, Any

import pandas as pd
import matplotlib.pyplot as plt
from jinja2 import Environment, FileSystemLoader

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False

from src.reporting.report_builder import ExperimentReport

logger = logging.getLogger(__name__)

class PDFGenerator:
    """Generates PDF reports from ExperimentReport objects."""
    
    def __init__(self, template_dir: Path, output_dir: Path) -> None:
        self.template_dir = template_dir
        self.output_dir = output_dir
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup Jinja2 environment
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))
        
        # Formatting filters
        self.env.filters["pct"] = lambda x: f"{x * 100:.2f}%" if x is not None else "N/A"
        self.env.filters["currency"] = lambda x: f"${x:.2f}" if x is not None else "N/A"
        self.env.filters["num"] = lambda x: f"{x:,}" if x is not None else "N/A"
        
        logger.debug("PDFGenerator initialised | template_dir=%s", template_dir)

    def generate(self, report: ExperimentReport) -> Path:
        """Generate the PDF report and return the file path."""
        if not WEASYPRINT_AVAILABLE:
            logger.error("WeasyPrint is not installed or dependencies are missing. PDF generation skipped.")
            return Path()
            
        output_filename = f"Experiment_Report_{report.experiment_name.replace(' ', '_')}.pdf"
        output_path = self.output_dir / output_filename
        
        try:
            # Generate charts as base64 strings
            charts = self._render_charts(report)
            
            # Render HTML from Jinja2 template
            html_content = self._render_template(report, charts)
            
            # Convert HTML to PDF
            HTML(string=html_content, base_url=str(self.template_dir)).write_pdf(str(output_path))
            
            logger.info("Successfully generated PDF report: %s", output_path)
            return output_path
            
        except Exception as e:
            logger.error("Failed to generate PDF report: %s", e)
            raise

    def _render_template(self, report: ExperimentReport, charts: Dict[str, str]) -> str:
        """Render the Jinja2 template to HTML."""
        template = self.env.get_template("report.html.j2")
        return template.render(
            report=report,
            charts=charts,
            date=report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        )

    def _render_charts(self, report: ExperimentReport) -> Dict[str, str]:
        """Generate all required charts as base64 encoded PNG strings."""
        charts = {}
        
        # We wrap in try-except so a single chart failure doesn't break the whole report
        try:
            if not report.daily_metrics.empty:
                charts["conversion_trend"] = self._generate_conversion_chart(report.daily_metrics)
        except Exception as e:
            logger.warning("Failed to generate conversion trend chart: %s", e)
            
        return charts

    def _generate_conversion_chart(self, daily_df: pd.DataFrame) -> str:
        """Generate cumulative conversion rate time series chart."""
        plt.figure(figsize=(10, 5))
        
        for variant in ["control", "variant"]:
            variant_data = daily_df[daily_df["variant"] == variant]
            if not variant_data.empty:
                plt.plot(
                    variant_data["metric_date"], 
                    variant_data["cumulative_conversion_rate"] * 100, 
                    label=variant.title(),
                    linewidth=2
                )
                
        plt.title("Cumulative Conversion Rate Over Time")
        plt.xlabel("Date")
        plt.ylabel("Conversion Rate (%)")
        plt.legend()
        plt.grid(True, linestyle="--", alpha=0.7)
        plt.tight_layout()
        
        return self._fig_to_base64()

    def _fig_to_base64(self) -> str:
        """Convert the current matplotlib figure to a base64 string."""
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150)
        plt.close()
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
