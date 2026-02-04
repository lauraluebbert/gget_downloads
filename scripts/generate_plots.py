#!/usr/bin/env python3
"""
Generate download plots from CSV data files.

Reads configuration from config.yaml and generates plots for all breakdowns.

Usage:
  # Generate all plots using config settings
  python scripts/generate_plots.py

  # Override plot days
  python scripts/generate_plots.py --plot-days 180

  # Generate specific breakdowns only
  python scripts/generate_plots.py --breakdowns daily country
"""
import argparse
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd
import yaml

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
PLOTS_DIR = PROJECT_ROOT / "plots"


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_csv_data(csv_path: Path) -> pd.DataFrame:
    """Load CSV data file."""
    if not csv_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    return df


def filter_last_n_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Filter to last N days of data."""
    if df.empty:
        return df

    today = pd.Timestamp(date.today())
    max_date = df["date"].max()
    end = min(today, max_date)
    start = end - pd.Timedelta(days=days - 1)

    return df[(df["date"] >= start) & (df["date"] <= end)].copy()


def plot_daily(df: pd.DataFrame, package: str, out_path: Path, fontsize: int = 12) -> None:
    """Plot daily download totals."""
    text_color = "grey"
    plot_color = "#fa8b59"

    df = df.sort_values("date")
    series = df.set_index("date")["downloads"]

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(series.index, series.values, color=plot_color, lw=2)

    ax.set_title(
        f"Daily {package} downloads — last {len(series)} days",
        fontsize=fontsize,
        color=text_color,
    )
    ax.set_xlabel("Date", fontsize=fontsize, color=text_color)
    ax.set_ylabel("Downloads", fontsize=fontsize, color=text_color)
    ax.set_ylim(bottom=0)
    ax.margins(x=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_color(text_color)

    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def plot_categorical(
    df: pd.DataFrame,
    package: str,
    breakdown: str,
    out_path: Path,
    fontsize: int = 12,
) -> None:
    """Plot categorical breakdown (python_major, python_minor, system)."""
    text_color = "grey"

    # Ensure category is string and filter out null/empty categories
    df = df.copy()
    df["category"] = df["category"].astype(str)
    plot_df = df[~df["category"].isin(["null", "None", "", "nan", "NaN"])].copy()

    if plot_df.empty:
        print(f"  Warning: No data to plot for {breakdown}")
        return

    # Pivot for plotting
    pivot = plot_df.pivot_table(
        index="date", columns="category", values="downloads", aggfunc="sum"
    ).fillna(0)

    # Sort columns appropriately
    if breakdown == "python_major":
        cols = sorted(pivot.columns, key=lambda x: (int(x) if str(x).isdigit() else 999, str(x)))
    elif breakdown == "python_minor":
        def version_key(v):
            try:
                parts = str(v).split(".")
                return tuple(int(p) for p in parts if p.isdigit())
            except (ValueError, AttributeError):
                return (999, 999)
        cols = sorted(pivot.columns, key=version_key)
    else:
        cols = sorted(pivot.columns)

    pivot = pivot[[c for c in cols if c in pivot.columns]]

    fig, ax = plt.subplots(figsize=(12, 4))

    cmap = plt.colormaps["tab10"]
    colors = [cmap(i % 10) for i in range(len(pivot.columns))]

    for i, col in enumerate(pivot.columns):
        ax.plot(pivot.index, pivot[col], color=colors[i], lw=1.5, label=col)

    breakdown_display = breakdown.replace("_", " ")
    ax.set_title(
        f"Daily {package} downloads by {breakdown_display} — last {len(pivot)} days",
        fontsize=fontsize,
        color=text_color,
    )
    ax.set_xlabel("Date", fontsize=fontsize, color=text_color)
    ax.set_ylabel("Downloads", fontsize=fontsize, color=text_color)
    ax.set_ylim(bottom=0)
    ax.margins(x=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_color(text_color)

    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=fontsize - 2, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def plot_alltime(df: pd.DataFrame, package: str, out_path: Path, fontsize: int = 12) -> None:
    """Plot all-time daily download totals (full history)."""
    text_color = "grey"
    plot_color = "#fa8b59"

    if df.empty:
        print("  Warning: No data to plot for all-time")
        return

    df = df.sort_values("date")
    series = df.set_index("date")["downloads"]

    # Calculate total downloads
    total = series.sum()
    start_date = series.index.min().strftime("%b %d, %Y")
    end_date = series.index.max().strftime("%b %d, %Y")

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(series.index, series.values, color=plot_color, lw=2)

    ax.set_title(
        f"Daily {package} downloads — all time ({start_date} to {end_date}) — {total:,} total",
        fontsize=fontsize,
        color=text_color,
    )
    ax.set_xlabel("Date", fontsize=fontsize, color=text_color)
    ax.set_ylabel("Downloads", fontsize=fontsize, color=text_color)
    ax.set_ylim(bottom=0)
    ax.margins(x=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_color(text_color)

    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def plot_country(
    df: pd.DataFrame,
    package: str,
    out_path: Path,
    top_n: int = 10,
    fontsize: int = 12,
) -> None:
    """Plot downloads by country (top N countries)."""
    text_color = "grey"

    if df.empty:
        print("  Warning: No data to plot for country")
        return

    # Get top N countries by total downloads
    totals = df.groupby("country_code")["downloads"].sum().sort_values(ascending=False)
    top_countries = totals.head(top_n).index.tolist()

    # Filter to top countries
    plot_df = df[df["country_code"].isin(top_countries)].copy()

    # Pivot for plotting
    pivot = plot_df.pivot_table(
        index="date", columns="country_code", values="downloads", aggfunc="sum"
    ).fillna(0)

    # Reorder by total downloads
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
    ax.margins(x=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_color(text_color)

    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", fontsize=fontsize - 2, framealpha=0.9, ncol=2)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate download plots from CSV data")
    parser.add_argument(
        "--plot-days",
        type=int,
        default=None,
        help="Number of days to show in plots (default: from config)",
    )
    parser.add_argument(
        "--breakdowns",
        nargs="+",
        default=None,
        help="Specific breakdowns to plot (default: all from config)",
    )
    args = parser.parse_args()

    config = load_config()
    package = config["package"]
    plot_days = args.plot_days or config["plot_days"]
    breakdowns = args.breakdowns or config["breakdowns"]

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating plots for '{package}' (last {plot_days} days)")

    for breakdown in breakdowns:
        print(f"\nProcessing: {breakdown}")

        csv_path = DATA_DIR / f"bigquery_{package}_{breakdown}.csv"
        if not csv_path.exists():
            print(f"  Warning: {csv_path} not found, skipping")
            continue

        df = load_csv_data(csv_path)
        df = filter_last_n_days(df, plot_days)

        if df.empty:
            print(f"  Warning: No data for {breakdown}")
            continue

        out_path = PLOTS_DIR / f"downloads_{package}_{breakdown}.png"

        if breakdown == "daily":
            plot_daily(df, package, out_path)
        elif breakdown == "country":
            plot_country(df, package, out_path)
        else:
            plot_categorical(df, package, breakdown, out_path)

        print(f"  Saved {out_path}")

    # Always generate all-time plot (ignores plot_days config)
    print("\nProcessing: all-time")
    daily_csv = DATA_DIR / f"bigquery_{package}_daily.csv"
    if daily_csv.exists():
        df = load_csv_data(daily_csv)
        if not df.empty:
            out_path = PLOTS_DIR / f"downloads_{package}_alltime.png"
            plot_alltime(df, package, out_path)
            print(f"  Saved {out_path}")
        else:
            print("  Warning: No data for all-time plot")
    else:
        print(f"  Warning: {daily_csv} not found, skipping all-time plot")

    print("\nDone!")


if __name__ == "__main__":
    main()
