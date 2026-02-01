#!/usr/bin/env python3
import argparse
from pathlib import Path
from datetime import date

import matplotlib
matplotlib.use("Agg")  # headless for CI
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd
import requests


def fetch_pypistats_categorical(package: str, endpoint: str) -> pd.DataFrame:
    """
    Fetch categorical pypistats data (python_major, python_minor, or system).
    Returns DataFrame with columns: date, category, downloads
    """
    url = f"https://pypistats.org/api/packages/{package}/{endpoint}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    payload = r.json()

    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "category", "downloads"])

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df["category"] = df["category"].astype(str)
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)

    return df[["date", "category", "downloads"]].sort_values(["date", "category"])


def load_categorical_history(csv_path: Path) -> pd.DataFrame:
    """Load existing categorical CSV history."""
    if not csv_path.exists():
        return pd.DataFrame(columns=["date", "category", "downloads"])
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df["category"] = df["category"].astype(str)
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    return df[["date", "category", "downloads"]].sort_values(["date", "category"])


def merge_categorical_history(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """
    Merge with 'new' taking precedence on overlapping (date, category) pairs.
    """
    if existing.empty and new.empty:
        return pd.DataFrame(columns=["date", "category", "downloads"])
    if existing.empty:
        merged = new.copy()
    elif new.empty:
        merged = existing.copy()
    else:
        combined = pd.concat([existing, new], ignore_index=True)
        # keep last occurrence per (date, category) — new appended later => wins
        merged = combined.sort_values(["date", "category"]).drop_duplicates(
            subset=["date", "category"], keep="last"
        )

    return merged.sort_values(["date", "category"]).reset_index(drop=True)


def ensure_continuous_daily_categorical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure there are no date gaps within each category: missing days => 0 downloads.
    """
    if df.empty:
        return df

    start = df["date"].min().normalize()
    end = df["date"].max().normalize()
    all_dates = pd.date_range(start=start, end=end, freq="D")
    categories = df["category"].unique()

    # Create full grid of (date, category)
    full_index = pd.MultiIndex.from_product([all_dates, categories], names=["date", "category"])
    full_df = pd.DataFrame(index=full_index).reset_index()

    # Merge with existing data
    merged = full_df.merge(df, on=["date", "category"], how="left")
    merged["downloads"] = merged["downloads"].fillna(0).astype(int)

    return merged.sort_values(["date", "category"]).reset_index(drop=True)


def last_n_days_categorical(df: pd.DataFrame, days: int = 365) -> pd.DataFrame:
    """
    Return last N days ending at today if possible, otherwise last N days available.
    """
    if df.empty:
        return df

    today = pd.Timestamp(date.today())
    max_date = df["date"].max()
    end = today if today <= max_date else max_date
    start = end - pd.Timedelta(days=days - 1)

    return df[(df["date"] >= start) & (df["date"] <= end)].copy()


def plot_categorical_series(
    df: pd.DataFrame,
    package: str,
    endpoint: str,
    out_path: Path,
    fontsize: int = 12,
) -> None:
    """
    Multi-line plot with one line per category.
    Filters out 'null' category from display.
    """
    text_color = "grey"

    # Filter out null category for plotting
    plot_df = df[df["category"] != "null"].copy()

    if plot_df.empty:
        raise SystemExit(f"No non-null data available to plot for {package}/{endpoint}")

    # Pivot to get categories as columns
    pivot = plot_df.pivot(index="date", columns="category", values="downloads").fillna(0)

    # Sort columns for consistent ordering
    if endpoint == "python_major":
        # Sort numerically: 2, 3
        cols = sorted(pivot.columns, key=lambda x: (int(x) if x.isdigit() else 999, x))
    elif endpoint == "python_minor":
        # Sort by version: 3.8, 3.9, 3.10, etc.
        def version_key(v):
            try:
                parts = v.split(".")
                return tuple(int(p) for p in parts)
            except (ValueError, AttributeError):
                return (999, 999)
        cols = sorted(pivot.columns, key=version_key)
    else:
        # system: alphabetical
        cols = sorted(pivot.columns)

    pivot = pivot[cols]

    fig, ax = plt.subplots(figsize=(12, 4))

    # Use a colormap for distinct colors
    cmap = plt.colormaps["tab10"]
    colors = [cmap(i % 10) for i in range(len(cols))]

    for i, col in enumerate(cols):
        ax.plot(pivot.index, pivot[col], color=colors[i], lw=1.5, label=col)

    # Format endpoint name for title
    endpoint_display = endpoint.replace("_", " ")
    ax.set_title(
        f"Daily {package} downloads by {endpoint_display} — last {len(pivot)} days",
        fontsize=fontsize,
        color=text_color,
    )
    ax.set_xlabel("Date", fontsize=fontsize, color=text_color)
    ax.set_ylabel("Downloads", fontsize=fontsize, color=text_color)
    ax.set_ylim(bottom=0)
    ax.tick_params(axis="both", labelsize=fontsize, colors=text_color)

    # Thousands separator on y-axis
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

    # Set axes spine color
    for spine in ax.spines.values():
        spine.set_color(text_color)

    # Grid
    ax.grid(True, axis="y", color=text_color, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)

    # Legend
    ax.legend(loc="upper left", fontsize=fontsize - 2, framealpha=0.9)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, transparent=True, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument(
        "--endpoint",
        required=True,
        choices=["python_major", "python_minor", "system"],
        help="pypistats categorical endpoint",
    )
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument(
        "--history-csv",
        default=None,
        help="Path to persisted CSV history (default: data/pypistats_<package>_<endpoint>.csv)",
    )
    args = parser.parse_args()

    package = args.package
    endpoint = args.endpoint
    out_png = Path(args.out)

    history_csv = (
        Path(args.history_csv)
        if args.history_csv
        else Path(f"data/pypistats_{package}_{endpoint}.csv")
    )
    history_csv.parent.mkdir(parents=True, exist_ok=True)

    # Fetch latest window from API
    new_df = fetch_pypistats_categorical(package, endpoint)

    # Merge into stored history
    existing_df = load_categorical_history(history_csv)
    merged_df = merge_categorical_history(existing_df, new_df)

    # Make continuous and save back to disk
    continuous_df = ensure_continuous_daily_categorical(merged_df)
    continuous_df.to_csv(history_csv, index=False)

    # Plot last 365 days (or max available)
    window_df = last_n_days_categorical(continuous_df, days=365)
    if window_df.empty:
        raise SystemExit(f"No data available to plot for package: {package}, endpoint: {endpoint}")

    plot_categorical_series(window_df, package, endpoint, out_png)


if __name__ == "__main__":
    main()
