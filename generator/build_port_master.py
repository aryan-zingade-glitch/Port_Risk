"""
Stage 1: Build port_master.csv — one row per port for all 60 ports.

Sources:
  - CPPI scores:  data/raw/cppi_annex_v2.xlsx (World Bank, CC BY 3.0 IGO)
  - LPI scores:   data/raw/lpi_2018.json (World Bank Data API, 2018 edition)
  - LSCI scores:  hardcoded from UNCTAD LSCI Q1 2023 published values
                  (Source: unctadstat.unctad.org/datacentre/dataviewer/US.LSCI)
  - Coordinates:  hardcoded from well-known port positions (WGS84)
  - GPR column:   mapping from port country ISO3 → GPR Excel column
"""

import pandas as pd
import openpyxl
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# 1. Port definitions: 60 ports with coordinates, region, country ISO3
# ---------------------------------------------------------------------------
PORTS = [
    # (locode, name, country, iso3, lat, lon, region, teu_tier)
    # teu_tier: 1=major hub >30M TEU/yr, 2=secondary 10-30M, 3=regional <10M

    # ASIA-PACIFIC (20)
    ("CNSHA", "Shanghai",          "China",           "CHN",  31.23,  121.47, "asia_pacific", 1),
    ("SGSIN", "Singapore",         "Singapore",       "SGP",   1.29,  103.85, "asia_pacific", 1),
    ("CNNGB", "Ningbo-Zhoushan",   "China",           "CHN",  29.87,  122.11, "asia_pacific", 1),
    ("CNSZX", "Shenzhen",          "China",           "CHN",  22.54,  114.06, "asia_pacific", 1),
    ("KRPUS", "Busan",             "South Korea",     "KOR",  35.18,  129.08, "asia_pacific", 1),
    ("HKHKG", "Hong Kong",         "Hong Kong",       "HKG",  22.32,  114.17, "asia_pacific", 1),
    ("CNGZU", "Guangzhou",         "China",           "CHN",  23.13,  113.26, "asia_pacific", 1),
    ("CNTAO", "Qingdao",           "China",           "CHN",  36.07,  120.38, "asia_pacific", 1),
    ("CNTXG", "Tianjin",           "China",           "CHN",  39.00,  117.72, "asia_pacific", 2),
    ("MYPKG", "Port Klang",        "Malaysia",        "MYS",   3.00,  101.40, "asia_pacific", 2),
    ("MYTPP", "Tanjung Pelepas",   "Malaysia",        "MYS",   1.36,  103.55, "asia_pacific", 2),
    ("IDJKT", "Jakarta",           "Indonesia",       "IDN",  -6.11,  106.88, "asia_pacific", 2),
    ("TWKHH", "Kaohsiung",         "Taiwan",          "TWN",  22.62,  120.30, "asia_pacific", 2),
    ("JPTYO", "Tokyo",             "Japan",           "JPN",  35.65,  139.75, "asia_pacific", 2),
    ("JPOSA", "Osaka",             "Japan",           "JPN",  34.65,  135.51, "asia_pacific", 2),
    ("PHMNL", "Manila",            "Philippines",     "PHL",  14.60,  120.98, "asia_pacific", 2),
    ("VNSGN", "Ho Chi Minh City",  "Vietnam",         "VNM",  10.78,  106.70, "asia_pacific", 2),
    ("THLCH", "Laem Chabang",      "Thailand",        "THA",  13.08,  100.88, "asia_pacific", 2),
    ("LKCMB", "Colombo",           "Sri Lanka",       "LKA",   6.93,   79.86, "asia_pacific", 2),
    ("INBOM", "Mumbai",            "India",           "IND",  18.92,   72.83, "asia_pacific", 2),

    # EUROPE (15)
    ("NLRTM", "Rotterdam",         "Netherlands",     "NLD",  51.92,    4.48, "europe",        1),
    ("BEANR", "Antwerp",           "Belgium",         "BEL",  51.30,    4.38, "europe",        1),
    ("DEHAM", "Hamburg",           "Germany",         "DEU",  53.58,    9.87, "europe",        2),
    ("GBFXT", "Felixstowe",        "United Kingdom",  "GBR",  51.96,    1.35, "europe",        2),
    ("ESVLC", "Valencia",          "Spain",           "ESP",  39.47,   -0.38, "europe",        2),
    ("ESALG", "Algeciras",         "Spain",           "ESP",  36.14,   -5.46, "europe",        2),
    ("GRPIR", "Piraeus",           "Greece",          "GRC",  37.94,   23.65, "europe",        2),
    ("ITGOA", "Genoa",             "Italy",           "ITA",  44.41,    8.95, "europe",        2),
    ("FRLEH", "Le Havre",          "France",          "FRA",  49.49,    0.11, "europe",        2),
    ("DEBRV", "Bremerhaven",       "Germany",         "DEU",  53.54,    8.58, "europe",        2),
    ("PLGDN", "Gdansk",            "Poland",          "POL",  54.35,   18.65, "europe",        3),
    ("ITGIT", "Gioia Tauro",       "Italy",           "ITA",  38.43,   15.90, "europe",        2),
    ("ESBCN", "Barcelona",         "Spain",           "ESP",  41.39,    2.17, "europe",        2),
    ("FRMRS", "Marseille",         "France",          "FRA",  43.30,    5.37, "europe",        2),
    ("ROCND", "Constanta",         "Romania",         "ROU",  44.16,   28.63, "europe",        3),

    # MIDDLE EAST / AFRICA (10)
    ("AEJEA", "Jebel Ali",         "UAE",             "ARE",  24.99,   55.03, "middle_east",   2),
    ("EGPSD", "Port Said",         "Egypt",           "EGY",  31.26,   32.30, "middle_east",   2),
    ("OMSLL", "Salalah",           "Oman",            "OMN",  16.94,   54.01, "middle_east",   2),
    ("SADMM", "Dammam",            "Saudi Arabia",    "SAU",  26.43,   50.10, "middle_east",   2),
    ("KEMBA", "Mombasa",           "Kenya",           "KEN",  -4.04,   39.67, "middle_east",   3),
    ("ZADUR", "Durban",            "South Africa",    "ZAF", -29.86,   31.02, "middle_east",   2),
    ("MATNG", "Tanger Med",        "Morocco",         "MAR",  35.88,   -5.52, "middle_east",   2),
    ("YEATH", "Aden",              "Yemen",           "YEM",  12.79,   45.02, "middle_east",   3),
    ("IRBND", "Bandar Abbas",      "Iran",            "IRN",  27.18,   56.27, "middle_east",   3),
    ("PKKHJ", "Karachi",           "Pakistan",        "PAK",  24.86,   67.00, "middle_east",   3),

    # AMERICAS (15)
    ("USLAX", "Los Angeles",       "United States",   "USA",  33.73, -118.26, "americas",      1),
    ("USLGB", "Long Beach",        "United States",   "USA",  33.75, -118.22, "americas",      1),
    ("USNYC", "New York",          "United States",   "USA",  40.68,  -74.04, "americas",      1),
    ("USSAV", "Savannah",          "United States",   "USA",  32.08,  -81.09, "americas",      2),
    ("USHOU", "Houston",           "United States",   "USA",  29.76,  -95.37, "americas",      2),
    ("BRSSZ", "Santos",            "Brazil",          "BRA", -23.96,  -46.33, "americas",      2),
    ("MXZLO", "Manzanillo MX",     "Mexico",          "MEX",  19.05, -104.32, "americas",      2),
    ("COCTG", "Cartagena",         "Colombia",        "COL",  10.42,  -75.55, "americas",      2),
    ("PAONX", "Colon",             "Panama",          "PAN",   9.36,  -79.90, "americas",      2),
    ("CAVAN",  "Vancouver",        "Canada",          "CAN",  49.28, -123.12, "americas",      2),
    ("USSEA", "Seattle",           "United States",   "USA",  47.61, -122.33, "americas",      2),
    ("USBAL", "Baltimore",         "United States",   "USA",  39.29,  -76.61, "americas",      3),
    ("USCHS", "Charleston",        "United States",   "USA",  32.78,  -79.93, "americas",      2),
    ("USNFK", "Norfolk",           "United States",   "USA",  36.85,  -76.29, "americas",      2),
    ("MXLZC", "Lazaro Cardenas",   "Mexico",          "MEX",  17.96, -102.17, "americas",      3),
]

# TEU calls per year by tier (approximate, used for synthetic generator)
TEU_CALLS = {1: 8000, 2: 4000, 3: 1500}

# ---------------------------------------------------------------------------
# 2. CPPI LOCODE mapping — some ports are listed under different codes
# ---------------------------------------------------------------------------
CPPI_LOCODE_MAP = {
    "CNSHA": "CNSHG",   # Shanghai (CPPI uses CNSHG)
    "CNNGB": "CNNBO",   # Ningbo-Zhoushan → Ningbo in CPPI
    "CNSZX": "CNYTN",   # Shenzhen → Yantian (largest Shenzhen terminal)
    "CNTAO": "CNQIN",   # Qingdao
    "CNTXG": "CNTNJ",   # Tianjin
    "CNGZU": "CNGGZ",   # Guangzhou
    "IDJKT": "IDCTO",   # Jakarta → Tanjung Priok
    "INBOM": "INNSA",   # Mumbai → JNPT (India's largest container port)
    "MATNG": "MAPTM",   # Tanger Med
    "YEATH": "YEADE",   # Aden
    "PKKHJ": "PKKHI",   # Karachi
}

# Ports with no CPPI equivalent — assign using nearest comparable port
# YEATH 2020: Aden not tracked until 2021; use 2021 value as proxy
CPPI_FALLBACK = {
    "IRBND": {"CPPI 2020": 60, "CPPI 2021": 30, "CPPI 2022": 25, "CPPI 2023": 40, "CPPI 2024": 20},
    "USNFK": {"CPPI 2020": 55, "CPPI 2021": 10, "CPPI 2022": -80, "CPPI 2023": 30, "CPPI 2024": 5},
}

# Per-year CPPI overrides for specific ports/years missing from the annex
CPPI_YEAR_OVERRIDES = {
    ("YEATH", 2020): -21,   # Aden: no 2020 data in CPPI; use 2021 value (-21) as nearest proxy
}

# ---------------------------------------------------------------------------
# 3. LSCI 2023 Q1 values by ISO3 country code
#    Source: UNCTAD LSCI quarterly, unctadstat.unctad.org/datacentre/dataviewer/US.LSCI
#    Values represent composite LSCI score (higher = better connected)
# ---------------------------------------------------------------------------
LSCI_2023 = {
    "CHN": 185.3, "SGP": 113.7, "KOR": 106.7, "DEU":  96.0, "NLD":  94.6,
    "BEL":  93.0, "JPN":  91.2, "MYS":  88.6, "USA":  85.2, "ESP":  82.4,
    "GBR":  81.4, "FRA":  79.3, "ITA":  76.5, "TWN":  74.8, "ARE":  77.3,
    "GRC":  68.2, "CAN":  68.3, "PAN":  62.4, "EGY":  61.8, "IND":  54.8,
    "AUS":  55.1, "VNM":  54.3, "BRA":  51.6, "OMN":  48.3, "SAU":  45.7,
    "THA":  43.2, "LKA":  42.1, "IDN":  45.2, "MEX":  48.3, "PHL":  35.4,
    "ZAF":  34.3, "COL":  28.4, "MAR":  52.1, "PAK":  27.8, "IRN":  24.3,
    "KEN":  18.2, "POL":  39.0, "ROU":  18.5, "YEM":   7.8, "HKG":  88.0,
}

# ---------------------------------------------------------------------------
# 4. GPR country column mapping (ISO3 → column name in gpr_data.xls)
# ---------------------------------------------------------------------------
GPR_COL_MAP = {
    # Direct matches (country has its own column in the GPR dataset)
    "CHN": "GPRHC_CHN",
    "KOR": "GPRHC_KOR", "DEU": "GPRHC_DEU", "NLD": "GPRHC_NLD",
    "BEL": "GPRHC_BEL", "JPN": "GPRHC_JPN", "MYS": "GPRHC_MYS",
    "USA": "GPRHC_USA", "ESP": "GPRHC_ESP", "GBR": "GPRHC_GBR",
    "FRA": "GPRHC_FRA", "ITA": "GPRHC_ITA", "TWN": "GPRHC_TWN",
    "SAU": "GPRHC_SAU", "CAN": "GPRHC_CAN", "IND": "GPRHC_IND",
    "BRA": "GPRHC_BRA", "THA": "GPRHC_THA", "IDN": "GPRHC_IDN",
    "MEX": "GPRHC_MEX", "PHL": "GPRHC_PHL", "ZAF": "GPRHC_ZAF",
    "COL": "GPRHC_COL", "HKG": "GPRHC_HKG", "AUS": "GPRHC_AUS",
    # Now directly available in the updated GPR file (gpr_updated.xls)
    "EGY": "GPRHC_EGY",   # Egypt — critical for Port Said / Red Sea analysis
    "VNM": "GPRHC_VNM",   # Vietnam — Ho Chi Minh City
    "POL": "GPRHC_POL",   # Poland — Gdansk
    # Regional proxies — nearest country with direct GPR coverage
    "SGP": "GPRHC_MYS",   # Singapore → Malaysia (same maritime sub-region)
    "ARE": "GPRHC_SAU",   # UAE → Saudi Arabia (Gulf Co-operation Council)
    "OMN": "GPRHC_SAU",   # Oman → Saudi Arabia (Gulf region)
    "GRC": "GPRHC_ITA",   # Greece → Italy (Mediterranean)
    "ROU": "GPRHC_TUR",   # Romania → Turkey (Black Sea / Eastern Med)
    "LKA": "GPRHC_IND",   # Sri Lanka → India (South Asia)
    "PAK": "GPRHC_IND",   # Pakistan → India (South Asia)
    "MAR": "GPRHC_ESP",   # Morocco → Spain (North Africa / Med)
    "IRN": "GPRHC_TUR",   # Iran → Turkey (Middle East / regional)
    "KEN": "GPRHC_ZAF",   # Kenya → South Africa (Sub-Saharan Africa)
    "YEM": "GPRHC_SAU",   # Yemen → Saudi Arabia (Red Sea / Gulf conflict zone)
    "PAN": "GPRHC_COL",   # Panama → Colombia (Latin America)
}


def load_cppi():
    wb = openpyxl.load_workbook(ROOT / "data/raw/cppi_annex_v2.xlsx", read_only=True)
    ws = wb["Annex"]
    rows = list(ws.iter_rows(values_only=True))
    df = pd.DataFrame(rows[1:], columns=rows[0])
    # Index by LOCODE for fast lookup
    return df.set_index("LOCODE")


def load_lpi():
    with open(ROOT / "data/raw/lpi_2018.json") as f:
        return json.load(f)


def build():
    cppi_df = load_cppi()
    lpi_data = load_lpi()

    records = []
    for (locode, name, country, iso3, lat, lon, region, teu_tier) in PORTS:
        cppi_locode = CPPI_LOCODE_MAP.get(locode, locode)

        if cppi_locode in cppi_df.index:
            row = cppi_df.loc[cppi_locode]
            cppi_2020 = row["CPPI 2020"]
            cppi_2021 = row["CPPI 2021"]
            cppi_2022 = row["CPPI 2022"]
            cppi_2023 = row["CPPI 2023"]
            cppi_2024 = row["CPPI 2024"]
            # Apply per-year overrides for missing data points
            for (lc, yr), val in CPPI_YEAR_OVERRIDES.items():
                if lc == locode:
                    if yr == 2020: cppi_2020 = val if (cppi_2020 is None or (isinstance(cppi_2020, float) and pd.isna(cppi_2020))) else cppi_2020
                    if yr == 2021: cppi_2021 = val if (cppi_2021 is None or (isinstance(cppi_2021, float) and pd.isna(cppi_2021))) else cppi_2021
        elif locode in CPPI_FALLBACK:
            fb = CPPI_FALLBACK[locode]
            cppi_2020 = fb["CPPI 2020"]
            cppi_2021 = fb["CPPI 2021"]
            cppi_2022 = fb["CPPI 2022"]
            cppi_2023 = fb["CPPI 2023"]
            cppi_2024 = fb["CPPI 2024"]
        else:
            cppi_2020 = cppi_2021 = cppi_2022 = cppi_2023 = cppi_2024 = None

        lpi = lpi_data.get(iso3)
        if iso3 == "TWN" and lpi is None:
            lpi = 3.83  # World Bank excludes Taiwan; assigned based on logistics infrastructure parity with KOR/JPN
        lsci = LSCI_2023.get(iso3)
        gpr_col = GPR_COL_MAP.get(iso3)
        annual_calls = TEU_CALLS[teu_tier]

        records.append({
            "locode": locode,
            "port_name": name,
            "country": country,
            "iso3": iso3,
            "lat": lat,
            "lon": lon,
            "region": region,
            "teu_tier": teu_tier,
            "annual_calls": annual_calls,
            "cppi_2020": cppi_2020,
            "cppi_2021": cppi_2021,
            "cppi_2022": cppi_2022,
            "cppi_2023": cppi_2023,
            "cppi_2024": cppi_2024,
            "lpi_score": lpi,
            "lsci_score": lsci,
            "gpr_col": gpr_col,
        })

    df = pd.DataFrame(records)

    # Validate: no port should have all 5 CPPI years as None
    missing_cppi = df[df[["cppi_2020","cppi_2021","cppi_2022","cppi_2023","cppi_2024"]].isnull().all(axis=1)]
    if not missing_cppi.empty:
        print(f"WARNING: {len(missing_cppi)} ports have no CPPI data:")
        print(missing_cppi[["locode","port_name"]].to_string())

    missing_lpi = df[df["lpi_score"].isnull()]
    if not missing_lpi.empty:
        print(f"WARNING: {len(missing_lpi)} ports have no LPI data:")
        print(missing_lpi[["locode","port_name","iso3"]].to_string())

    out = ROOT / "data/processed/port_master.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df)} ports to {out}")
    return df


if __name__ == "__main__":
    df = build()
    print("\n=== SUMMARY ===")
    print(f"Total ports: {len(df)}")
    print(f"Regions: {df['region'].value_counts().to_dict()}")
    print(f"CPPI coverage: {df['cppi_2024'].notna().sum()}/60 ports have 2024 data")
    print(f"LPI coverage:  {df['lpi_score'].notna().sum()}/60 ports have LPI data")
    print(f"LSCI coverage: {df['lsci_score'].notna().sum()}/60 ports have LSCI data")
    print("\nSample rows:")
    print(df[["locode","port_name","cppi_2024","lpi_score","lsci_score"]].head(10).to_string())
