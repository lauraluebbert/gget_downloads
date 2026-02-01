#!/usr/bin/env python3
"""
Fetch PyPI download statistics from BigQuery.

Supports multiple breakdown types:
  - daily: Total downloads per day
  - python_major: Downloads by Python major version
  - python_minor: Downloads by Python minor version
  - system: Downloads by operating system
  - country: Downloads by country code

Usage:
  # Initial historical fetch (from start_date in config)
  python scripts/fetch_bigquery_stats.py --initial

  # Incremental update (last N days, default 10)
  python scripts/fetch_bigquery_stats.py --days 10

  # Fetch specific breakdowns only
  python scripts/fetch_bigquery_stats.py --breakdowns daily country
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

try:
    from google.cloud import bigquery
except ImportError:
    raise ImportError(
        "google-cloud-bigquery is required. Install with: pip install google-cloud-bigquery"
    )

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_breakdown_query(breakdown: str) -> tuple[str, list[str]]:
    """
    Return the SQL query template and output columns for a breakdown type.

    Returns:
        (query_template, columns)
    """
    queries = {
        "daily": (
            """
            SELECT
                DATE(timestamp) as date,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date
            ORDER BY date
            """,
            ["date", "downloads"],
        ),
        "python_major": (
            """
            SELECT
                DATE(timestamp) as date,
                SPLIT(details.python, '.')[SAFE_OFFSET(0)] as category,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date, category
            ORDER BY date, category
            """,
            ["date", "category", "downloads"],
        ),
        "python_minor": (
            """
            SELECT
                DATE(timestamp) as date,
                CONCAT(
                    SPLIT(details.python, '.')[SAFE_OFFSET(0)], '.',
                    SPLIT(details.python, '.')[SAFE_OFFSET(1)]
                ) as category,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date, category
            ORDER BY date, category
            """,
            ["date", "category", "downloads"],
        ),
        "system": (
            """
            SELECT
                DATE(timestamp) as date,
                details.system.name as category,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date, category
            ORDER BY date, category
            """,
            ["date", "category", "downloads"],
        ),
        "country": (
            """
            SELECT
                DATE(timestamp) as date,
                country_code,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date, country_code
            ORDER BY date, country_code
            """,
            ["date", "country_code", "downloads"],
        ),
        "mirrors": (
            """
            SELECT
                DATE(timestamp) as date,
                'with_mirrors' as category,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
            GROUP BY date

            UNION ALL

            SELECT
                DATE(timestamp) as date,
                'without_mirrors' as category,
                COUNT(*) as downloads
            FROM `bigquery-public-data.pypi.file_downloads`
            WHERE project = @package
                AND DATE(timestamp) >= @start_date
                AND DATE(timestamp) <= @end_date
                AND country_code IS NOT NULL
            GROUP BY date

            ORDER BY date, category
            """,
            ["date", "category", "downloads"],
        ),
    }
    return queries[breakdown]


def fetch_breakdown(
    client: bigquery.Client,
    package: str,
    breakdown: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Fetch a specific breakdown from BigQuery.
    """
    query_template, columns = get_breakdown_query(breakdown)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("package", "STRING", package),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    print(f"  Querying {breakdown} from {start_date} to {end_date}...")
    query_job = client.query(query_template, job_config=job_config)
    results = query_job.result()

    df = results.to_dataframe()
    if df.empty:
        return pd.DataFrame(columns=columns)

    # Normalize column types
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)

    # Handle category/country_code column
    if "category" in df.columns:
        df["category"] = df["category"].fillna("null").astype(str)
    if "country_code" in df.columns:
        df["country_code"] = df["country_code"].fillna("Unknown").astype(str)

    return df[columns].sort_values(columns[:-1])  # Sort by all columns except downloads


def get_csv_path(package: str, breakdown: str) -> Path:
    """Get the CSV path for a breakdown."""
    return DATA_DIR / f"bigquery_{package}_{breakdown}.csv"


def load_existing_data(csv_path: Path, columns: list[str]) -> pd.DataFrame:
    """Load existing CSV data if it exists."""
    if not csv_path.exists():
        return pd.DataFrame(columns=columns)

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)

    if "category" in df.columns:
        df["category"] = df["category"].astype(str)
    if "country_code" in df.columns:
        df["country_code"] = df["country_code"].astype(str)

    return df[columns]


def merge_data(existing: pd.DataFrame, new: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    """
    Merge existing and new data, with new data taking precedence on conflicts.
    """
    if existing.empty:
        return new.copy()
    if new.empty:
        return existing.copy()

    combined = pd.concat([existing, new], ignore_index=True)
    # Keep last occurrence (new data) for duplicates
    merged = combined.sort_values(key_columns).drop_duplicates(subset=key_columns, keep="last")
    return merged.sort_values(key_columns).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch PyPI download stats from BigQuery")
    parser.add_argument(
        "--initial",
        action="store_true",
        help="Fetch all historical data from start_date in config",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of days to fetch for incremental update (default: 10)",
    )
    parser.add_argument(
        "--breakdowns",
        nargs="+",
        default=None,
        help="Specific breakdowns to fetch (default: all from config)",
    )
    args = parser.parse_args()

    config = load_config()
    package = config["package"]
    breakdowns = args.breakdowns or config["breakdowns"]

    # Determine date range
    # Note: BigQuery data typically has 1-day lag, so we end at yesterday
    end_date = date.today() - timedelta(days=1)

    if args.initial:
        start_date = date.fromisoformat(config["start_date"])
        print(f"Initial fetch for '{package}' from {start_date} to {end_date}")
    else:
        start_date = end_date - timedelta(days=args.days - 1)
        print(f"Incremental fetch for '{package}' from {start_date} to {end_date}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client()

    for breakdown in breakdowns:
        print(f"\nProcessing breakdown: {breakdown}")

        _, columns = get_breakdown_query(breakdown)
        key_columns = [c for c in columns if c != "downloads"]

        # Fetch new data
        new_df = fetch_breakdown(client, package, breakdown, start_date, end_date)
        print(f"  Fetched {len(new_df)} rows")

        # Load existing and merge
        csv_path = get_csv_path(package, breakdown)
        existing_df = load_existing_data(csv_path, columns)
        merged_df = merge_data(existing_df, new_df, key_columns)

        # Save
        merged_df.to_csv(csv_path, index=False)
        print(f"  Saved {len(merged_df)} total rows to {csv_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
