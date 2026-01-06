# Daily gget downloads tracking

This repository tracks **daily PyPI download counts for [gget](https://pachterlab.github.io/gget/)** using the
[pypistats](https://pypistats.org) API.

A GitHub Actions workflow runs once per day to:
1. Fetch the latest available daily download data from pypistats
2. **Persist the data locally in the repository** (building a stable historical record over time)
3. Merge new data with previously captured days to avoid API window truncation
4. Generate and commit an updated plot showing the **last 365 days (or maximum available)** of downloads

This approach ensures that older download data is preserved even when the API
only returns a limited recent window, and guarantees a consistent long-term
time series going forward.


![gget PyPI downloads over the last year](plots/downloads_gget.png)

## Output
- `plots/downloads_gget.png`

Automatically runs daily via GitHub Actions.

## Repository structure

```text
.
├── .github/
│   └── workflows/
│       └── downloads-plot.yml
├── scripts/
│   └── plot_downloads.py
├── plots/
│   └── .gitkeep
├── data/
│   └── .gitkeep
├── requirements.txt
├── .gitignore
└── README.md
```
