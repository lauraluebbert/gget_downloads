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
    pypistats overall endpoint returns daily downloads for a recent window
    (typically up to ~365 days). Response shape includes:
      {"data": [{"category": "without_mirrors", "date": "YYYY-MM-DD", "downloads": N}, ...]}
    """
    url = f"https://pypistats.org/api/packages/{package}/overall"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    payload = r.json()

    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "downloads"])

    df = pd.DataFrame(data)

    # Prefer "without_mirrors" if present; otherwise use whatever is there.
    if "category" in df.columns:
        if (df["category"] == "without_mirrors").any():
            df = df[df["category"] == "without_mirrors"].copy()
        else:
            # fall back to the first category present
            df = df[df["category"] == df["category"].iloc[0]].copy()

    df["date"] = pd.to_datetime(df["date"])
    df["downloads"] = pd.to_numeric(df["downloads"], errors="coerce").fillna(0).astype(int)
    df = df.sort_values("date")

    return df[["date", "downloads"]]


def ensure_last_year_series(df: pd.DataFrame) -> pd.Series:
    """
    Create a continuous daily series for the last 365 days ending today.
    Missing dates filled with 0.
    """
    end = date.today()
    start = end - timedelta(days=364)
    idx = pd.date_range(start=start, end=end, freq="D")

    if df.empty:
        return pd.Series(0, index=idx, name="downloads")

    s = df.set_index("date")["downloads"]
    s = s.reindex(idx, fill_value=0)
    s.name = "downloads"
    return s


def plot_series(series: pd.Series, package: str, out_path: str) -> None:
    plt.figure(figsize=(12, 5))
    plt.plot(series.index, series.values)
    plt.title(f"PyPI downloads (pypistats) — last 365 days — {package}")
    plt.xlabel("Date")
    plt.ylabel("Downloads")
    plt.tight_layout()

    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=150)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    df = fetch_pypistats_daily(args.package)
    series = ensure_last_year_series(df)
    plot_series(series, args.package, args.out)


if __name__ == "__main__":
    main()
