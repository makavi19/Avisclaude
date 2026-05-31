"""
CSV Data Loader — handles MT4, MT5, and generic OHLCV formats.
Supports loading multiple yearly files from a folder.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd


# ── Column name normalisation ─────────────────────────────────────────────────

_COL_MAP = {
    # Date/time variants
    "date": "date", "<date>": "date", "datetime": "datetime",
    "time": "time", "<time>": "time",
    "timestamp": "datetime",
    # OHLCV variants
    "open": "open", "<open>": "open",
    "high": "high", "<high>": "high",
    "low": "low", "<low>": "low",
    "close": "close", "<close>": "close",
    "volume": "volume", "<tickvol>": "volume", "<vol>": "volume",
    "tickvol": "volume", "vol": "volume", "tick_volume": "volume",
    # Ignored
    "<spread>": None, "spread": None,
}

_DATE_FORMATS = [
    "%Y.%m.%d %H:%M",     # MT4/MT5:  2015.01.02 00:01
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",  # ISO
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%Y%m%d %H%M%S",      # compact: 20150102 000100
]


def _parse_datetime_series(series: pd.Series) -> pd.Series:
    for fmt in _DATE_FORMATS:
        try:
            return pd.to_datetime(series, format=fmt)
        except Exception:
            pass
    return pd.to_datetime(series, infer_datetime_format=True)


def load_csv_file(path: str | Path) -> pd.DataFrame:
    """
    Load one CSV file. Auto-detects MT4, MT5, and generic formats.
    Returns DataFrame indexed by UTC datetime with columns: open, high, low, close, volume.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    # Detect delimiter from first line
    with open(path, encoding="utf-8", errors="replace") as f:
        first_line = f.readline()
    delimiter = "\t" if "\t" in first_line else ","

    df = pd.read_csv(path, sep=delimiter, dtype=str, skipinitialspace=True)

    # Normalise column names
    rename = {}
    drop_cols = []
    for col in df.columns:
        key = col.strip().lower()
        mapped = _COL_MAP.get(key, key)  # keep unknown names as-is
        if mapped is None:
            drop_cols.append(col)
        elif mapped != col:
            rename[col] = mapped
    df = df.rename(columns=rename)
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    # Build datetime index
    if "datetime" in df.columns:
        dt = _parse_datetime_series(df["datetime"])
    elif "date" in df.columns and "time" in df.columns:
        dt = _parse_datetime_series(df["date"].str.strip() + " " + df["time"].str.strip())
        df = df.drop(columns=["date", "time"])
    elif "date" in df.columns:
        dt = _parse_datetime_series(df["date"])
        df = df.drop(columns=["date"])
    else:
        raise ValueError(f"Cannot find date/time columns in {path}. Columns: {list(df.columns)}")

    df.index = dt
    df.index.name = "datetime"

    # Keep only OHLCV, cast to float
    needed = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[needed].apply(pd.to_numeric, errors="coerce")

    if "volume" not in df.columns:
        df["volume"] = 1.0

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_index()
    return df


def load_data_folder(
    folder: str | Path,
    instrument: str = "",
    year_start: int | None = None,
    year_end: int | None = None,
) -> pd.DataFrame:
    """
    Load all CSV files from a folder (one per year).
    Filters by year_start/year_end if provided.
    Files can be named anything — sorted by filename.
    """
    folder = Path(folder)
    csv_files = sorted(folder.glob("*.csv")) + sorted(folder.glob("*.CSV"))

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {folder}")

    frames: list[pd.DataFrame] = []
    for f in csv_files:
        # Try to extract year from filename
        year_match = re.search(r"(20\d{2}|19\d{2})", f.stem)
        if year_match:
            yr = int(year_match.group(1))
            if year_start and yr < year_start:
                continue
            if year_end and yr > year_end:
                continue
        try:
            df = load_csv_file(f)
            frames.append(df)
            print(f"  Loaded {f.name}: {len(df):,} bars  ({df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d})")
        except Exception as exc:
            print(f"  WARNING: Skipping {f.name}: {exc}")

    if not frames:
        raise ValueError("No data loaded — check folder path and year filters.")

    combined = pd.concat(frames).sort_index()
    # Remove exact duplicates
    combined = combined[~combined.index.duplicated(keep="first")]
    return combined


def resample_to_timeframe(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample 1-minute OHLCV data to a higher timeframe.
    timeframe: 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'
    """
    tf_map = {
        "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
        "H1": "1h", "H4": "4h", "D1": "1D",
    }
    rule = tf_map.get(timeframe.upper())
    if rule is None:
        raise ValueError(f"Unknown timeframe: {timeframe}. Use M5, M15, M30, H1, H4, D1.")

    ohlc_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    resampled = df_1m.resample(rule, label="left", closed="left").agg(ohlc_dict)
    return resampled.dropna(subset=["open", "close"])
