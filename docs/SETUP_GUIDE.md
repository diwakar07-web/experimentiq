# ExperimentIQ Setup Guide

Follow these steps to set up the ExperimentIQ pipeline locally.

## 1. Prerequisites
- **Operating System:** Windows, macOS, or Linux
- **Python:** 3.12 or newer
- **Docker & Docker Compose:** Required to run the local PostgreSQL instance.

## 2. Installation

Clone the repository to your local machine:
```bash
git clone <repository_url>
cd ExperimentIQ
```

Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

Install the required Python packages:
```bash
pip install -r requirements.txt
```

## 3. Environment Configuration

Copy the example environment file and customize it if needed:
```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```
The `.env` file controls the database connection and generation scale. The default values generate a small dataset suitable for local testing.

## 4. Start the Database

Start the PostgreSQL database using Docker Compose:
```bash
docker-compose up -d
```
Wait a few seconds for the database to initialize.

## 5. Initialize the Database Schema

Run the seed script to create the tables, views, and lookup data:
```bash
python database/seed.py
```
This will insert the necessary reference data (countries, devices, channels).

## 6. Run the Pipeline

You can now run the end-to-end pipeline. The pipeline handles data generation, database ingestion, metric computation, statistical analysis, and report generation.

```bash
python run_pipeline.py
```

### Pipeline Options
- `--dry-run`: Validates the configuration and checks database connectivity without running the data generation or ingestion.
- `--skip-generation`: Skips data generation and loads existing CSVs from `data/raw/` (useful for re-running the analytics layer on the same data).

## 7. Connecting Power BI
After the pipeline finishes, it exports CSV files to `data/exports/`. You can connect Power BI Desktop to these CSV files using the "Text/CSV" connector. Follow the `dashboards/DASHBOARD_GUIDE.md` for specific dashboard configurations.
