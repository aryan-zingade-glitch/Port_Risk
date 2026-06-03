"""
Parse GPR (Geopolitical Risk Index) Excel file.

Source: Caldara & Iacoviello
  Main file: https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls
  Updated through May 2026 (as of June 2026 download)
  License: Creative Commons Attribution 4.0

Output: data/processed/gpr_monthly.csv
  Columns: date, year, month, gpr_global, GPRHC_XXX (country-specific)
  Filtered to 2020-2024
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent


def parse_gpr():
    df_raw = pd.read_excel(ROOT / "data/raw/gpr_updated.xls", sheet_name="Sheet1")

    df_raw["date"] = pd.to_datetime(df_raw["month"], errors="coerce")
    df_raw = df_raw.dropna(subset=["date"])
    df_raw["year"] = df_raw["date"].dt.year
    df_raw["month_num"] = df_raw["date"].dt.month

    df = df_raw[(df_raw["year"] >= 2020) & (df_raw["year"] <= 2024)].copy()

    # Country-specific columns (GPRHC_XXX = country-level geopolitical risk)
    country_cols = [c for c in df.columns if c.startswith("GPRHC_")]

    keep = ["date", "year", "month_num", "GPR", "GPRH"] + country_cols
    df = df[keep].reset_index(drop=True)
    df = df.rename(columns={"month_num": "month", "GPR": "gpr_global", "GPRH": "gpr_historical"})

    print(f"GPR monthly records 2020-2024: {len(df)}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Global GPR range: {df['gpr_global'].min():.1f} to {df['gpr_global'].max():.1f}")
    print(f"Country columns ({len(country_cols)}): {country_cols}")
    print("\nSample (showing COVID peak and Red Sea period):")
    highlights = df[df["date"].isin(pd.to_datetime([
        "2020-03-01", "2021-03-01", "2022-02-01", "2023-12-01", "2024-01-01"
    ]))]
    print(highlights[["date", "gpr_global"]].to_string())

    out = ROOT / "data/processed/gpr_monthly.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved to {out}")
    return df


if __name__ == "__main__":
    parse_gpr()
