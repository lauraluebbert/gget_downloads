#!/usr/bin/env python3
import argparse
from pathlib import Path
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")  # headless for CI
import matplotlib.pyplot as plt
import pandas as pd
import requests


def fetch_pypistats_daily(package: str) -> pd.DataFrame:
    """
    pypistats 'overall' endpoint:
    - daily downloads for the *package* aggregated across ALL releases/versions on PyPI
    - may include multiple categories (with_mirrors / without_mirrors) with different coverage windows
    We select the category with the longest date coverage to avoid truncation surprises.
    """
    url = f"https://pypistats.org/api/packages/{package}/overall"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    payload = r.json()

    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "downloads"])

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)

    if "category" in df.columns and not df.empty:
        coverage = df.groupby("category")["date"].nunique().sort_values(ascending=False)
        best_category = coverage.index[0]
        df = df[df["category"] == best_category].copy()

    df = df.sort_values("date")
    return df[["date", "downloads"]]


def load_history(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=["date", "downloads"])
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    return df[["date", "downloads"]].sort_values("date")


def merge_history(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """
    Merge with 'new' taking precedence on overlapping dates.
    """
    if existing.empty and new.empty:
        return pd.DataFrame(columns=["date", "downloads"])
    if existing.empty:
        merged = new.copy()
    elif new.empty:
        merged = existing.copy()
    else:
        combined = pd.concat([existing, new], ignore_index=True)
        # keep last occurrence per date (new appended later => wins)
        merged = combined.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    return merged.sort_values("date").reset_index(drop=True)


def ensure_continuous_daily(df: pd.DataFrame) -> pd.Series:
    """
    Ensure there are no gaps inside the stored date range: missing days => 0.
    """
    if df.empty:
        return pd.Series(dtype=int)

    start = df["date"].min().normalize()
    end = df["date"].max().normalize()
    idx = pd.date_range(start=start, end=end, freq="D")
    s = df.set_index("date")["downloads"].reindex(idx, fill_value=0)
    s.name = "downloads"
    return s


def last_n_days(series: pd.Series, days: int = 365) -> pd.Series:
    """
    Return last N days ending at today if possible, otherwise last N points available.
    We don't invent future values.
    """
    if series.empty:
        return series

    today = pd.Timestamp(date.today())
    # If we have today, anchor to today; otherwise anchor to last available day.
    end = today if today in series.index else series.index.max()
    start = end - pd.Timedelta(days=days - 1)

    # slice within existing index
    out = series.loc[(series.index >= start) & (series.index <= end)]
    return out

def plot_series(
    series: pd.Series,
    package: str,
    out_path: Path,
    fontsize: int = 12,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(series.index, series.values, color="darkorange", lw=2)

    ax.set_title(
        f"Daily {package} downloads (pypistats) — last {len(series)} days",
        fontsize=fontsize,
    )
    ax.set_xlabel("Date", fontsize=fontsize)
    ax.set_ylabel("Downloads", fontsize=fontsize)

    ax.tick_params(axis="both", labelsize=fontsize)

    ax.grid(True, axis="y", color="lightgrey", linestyle="--", linewidth=1)
    ax.set_axisbelow(True)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument(
        "--history-csv",
        default=None,
        help="Path to persisted CSV history (default: data/pypistats_<package>_daily.csv)",
    )
    args = parser.parse_args()

    package = args.package
    out_png = Path(args.out)

    history_csv = Path(args.history_csv) if args.history_csv else Path(f"data/pypistats_{package}_daily.csv")
    history_csv.parent.mkdir(parents=True, exist_ok=True)

    # Fetch latest window from API
    new_df = fetch_pypistats_daily(package)

    # Merge into stored history
    existing_df = load_history(history_csv)
    merged_df = merge_history(existing_df, new_df)

    # Make continuous and save back to disk
    merged_series = ensure_continuous_daily(merged_df)
    merged_series.to_frame().reset_index().rename(columns={"index": "date"}).to_csv(history_csv, index=False)

    # Plot last 365 days (or max available)
    window = last_n_days(merged_series, days=365)
    if window.empty:
        raise SystemExit(f"No data available to plot for package: {package}")

    plot_series(window, package, out_png)


if __name__ == "__main__":
    main()
