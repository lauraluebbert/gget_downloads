#!/usr/bin/env python3
import argparse
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")  # headless for CI
import matplotlib.pyplot as plt
import pandas as pd
import requests


def fetch_pypistats_daily(package: str) -> pd.DataFrame:
    """
    Uses pypistats "overall" endpoint:
    - Returns daily downloads aggregated for the *package* across all releases/versions on PyPI.
    - We prefer 'without_mirrors' when available to reduce noise.
    """
    url = f"https://pypistats.org/api/packages/{package}/overall"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    payload = r.json()

    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "downloads"])

    df = pd.DataFrame(data)

    # Prefer without_mirrors if present; otherwise fall back to first available category.
    if "category" in df.columns and not df.empty:
        if (df["category"] == "without_mirrors").any():
            df = df[df["category"] == "without_mirrors"].copy()
        else:
            df = df[df["category"] == df["category"].iloc[0]].copy()

    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    df = df.sort_values("date")

    return df[["date", "downloads"]]


def ensure_last_year_series(df: pd.DataFrame) -> pd.Series:
    """Continuous daily series for the last 365 days ending today; missing dates filled with 0."""
    end = date.today()
    start = end - timedelta(days=364)
    idx = pd.date_range(start=start, end=end, freq="D")

    if df.empty:
        return pd.Series(0, index=idx, name="downloads")

    s = df.set_index("date")["downloads"].reindex(idx, fill_value=0)
    s.name = "downloads"
    return s


def plot_series(series: pd.Series, package: str, out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))

    # Line color left as default (Matplotlib picks it)
    ax.plot(series.index, series.values)

    ax.set_title(f"PyPI downloads (pypistats) — last 365 days — {package}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Downloads")

    # Light grey grid on Y axis only
    ax.grid(True, axis="y", color="lightgrey")

    fig.tight_layout()

    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    df = fetch_pypistats_daily(args.package)

    # This is already "all versions/releases" of the package because the endpoint is package-level,
    # and we do not filter on version or filename.
    series = ensure_last_year_series(df)

    plot_series(series, args.package, args.out)


if __name__ == "__main__":
    main()
