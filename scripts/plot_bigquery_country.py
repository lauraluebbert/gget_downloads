#!/usr/bin/env python3
"""
Fetch and plot gget download counts by country from BigQuery.

Requires:
  - google-cloud-bigquery package
  - Authentication via one of:
    - GOOGLE_APPLICATION_CREDENTIALS environment variable pointing to a service account JSON
    - Application Default Credentials (gcloud auth application-default login)
    - Workload Identity (in GCP environments)
"""
import argparse
from pathlib import Path
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd

try:
    from google.cloud import bigquery
except ImportError:
    raise ImportError(
        "google-cloud-bigquery is required. Install with: pip install google-cloud-bigquery"
    )


def fetch_country_downloads(package: str, days: int = 180) -> pd.DataFrame:
    """
    Query BigQuery for daily download counts by country.

    Note: BigQuery public PyPI dataset typically has ~1 day lag.
    We query the last N days to get recent data.
    """
    client = bigquery.Client()

    query = f"""
    SELECT
        DATE(timestamp) as date,
        country_code,
        COUNT(*) as downloads
    FROM `bigquery-public-data.pypi.file_downloads`
    WHERE project = @package
        AND DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    GROUP BY date, country_code
    ORDER BY date, downloads DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("package", "STRING", package),
            bigquery.ScalarQueryParameter("days", "INT64", days),
        ]
    )

    query_job = client.query(query, job_config=job_config)
    results = query_job.result()

    df = results.to_dataframe()
    if df.empty:
        return pd.DataFrame(columns=["date", "country_code", "downloads"])

    df["date"] = pd.to_datetime(df["date"])
    df["country_code"] = df["country_code"].fillna("Unknown").astype(str)
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)

    return df[["date", "country_code", "downloads"]].sort_values(["date", "country_code"])


def load_country_history(csv_path: Path) -> pd.DataFrame:
    """Load existing country CSV history."""
    if not csv_path.exists():
        return pd.DataFrame(columns=["date", "country_code", "downloads"])
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df["country_code"] = df["country_code"].astype(str)
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    return df[["date", "country_code", "downloads"]].sort_values(["date", "country_code"])


def merge_country_history(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """
    Merge with 'new' taking precedence on overlapping (date, country_code) pairs.
    """
    if existing.empty and new.empty:
        return pd.DataFrame(columns=["date", "country_code", "downloads"])
    if existing.empty:
        merged = new.copy()
    elif new.empty:
        merged = existing.copy()
    else:
        combined = pd.concat([existing, new], ignore_index=True)
        merged = combined.sort_values(["date", "country_code"]).drop_duplicates(
            subset=["date", "country_code"], keep="last"
        )

    return merged.sort_values(["date", "country_code"]).reset_index(drop=True)


def get_top_countries(df: pd.DataFrame, top_n: int = 10) -> list:
    """Get the top N countries by total downloads."""
    totals = df.groupby("country_code")["downloads"].sum().sort_values(ascending=False)
    return totals.head(top_n).index.tolist()


def last_n_days_country(df: pd.DataFrame, days: int = 180) -> pd.DataFrame:
    """Return last N days of data."""
    if df.empty:
        return df

    today = pd.Timestamp(date.today())
    max_date = df["date"].max()
    end = today if today <= max_date else max_date
    start = end - pd.Timedelta(days=days - 1)

    return df[(df["date"] >= start) & (df["date"] <= end)].copy()


def plot_country_downloads(
    df: pd.DataFrame,
    package: str,
    out_path: Path,
    top_n: int = 10,
    fontsize: int = 12,
) -> None:
    """
    Plot downloads by country (top N countries as separate lines).
    """
    text_color = "grey"

    if df.empty:
        raise SystemExit(f"No data available to plot for {package}")

    # Get top countries
    top_countries = get_top_countries(df, top_n)

    # Filter to top countries only
    plot_df = df[df["country_code"].isin(top_countries)].copy()

    # Pivot for plotting
    pivot = plot_df.pivot_table(
        index="date",
        columns="country_code",
        values="downloads",
        aggfunc="sum"
    ).fillna(0)

    # Reorder columns by total downloads
    col_order = [c for c in top_countries if c in pivot.columns]
    pivot = pivot[col_order]

    fig, ax = plt.subplots(figsize=(12, 5))

    cmap = plt.colormaps["tab10"]
    colors = [cmap(i % 10) for i in range(len(col_order))]

    for i, col in enumerate(col_order):
        ax.plot(pivot.index, pivot[col], color=colors[i], lw=1.5, label=col)

    ax.set_title(
        f"Daily {package} downloads by country (top {len(col_order)}) — last {len(pivot)} days",
        fontsize=fontsize,
        color=text_color,
    )
    ax.set_xlabel("Date", fontsize=fontsize, color=text_color)
    ax.set_ylabel("Downloads", fontsize=fontsize, color=text_color)
    ax.set_ylim(bottom=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)

    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_color(text_color)

    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)

    ax.legend(loc="upper left", fontsize=fontsize - 2, framealpha=0.9, ncol=2)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and plot PyPI downloads by country from BigQuery"
    )
    parser.add_argument("--package", required=True, help="PyPI package name")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument(
        "--history-csv",
        default=None,
        help="Path to persisted CSV history (default: data/bigquery_<package>_country.csv)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of top countries to show in plot (default: 10)",
    )
    parser.add_argument(
        "--query-days",
        type=int,
        default=180,
        help="Number of days to query from BigQuery (default: 180)",
    )
    parser.add_argument(
        "--plot-days",
        type=int,
        default=180,
        help="Number of days to show in plot (default: 180)",
    )
    args = parser.parse_args()

    package = args.package
    out_png = Path(args.out)

    history_csv = (
        Path(args.history_csv)
        if args.history_csv
        else Path(f"data/bigquery_{package}_country.csv")
    )
    history_csv.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching country downloads for '{package}' from BigQuery...")
    new_df = fetch_country_downloads(package, days=args.query_days)
    print(f"  Fetched {len(new_df)} rows")

    existing_df = load_country_history(history_csv)
    merged_df = merge_country_history(existing_df, new_df)

    merged_df.to_csv(history_csv, index=False)
    print(f"  Saved history to {history_csv}")

    window_df = last_n_days_country(merged_df, days=args.plot_days)
    if window_df.empty:
        raise SystemExit(f"No data available to plot for package: {package}")

    plot_country_downloads(window_df, package, out_png, top_n=args.top_n)
    print(f"  Saved plot to {out_png}")


if __name__ == "__main__":
    main()
