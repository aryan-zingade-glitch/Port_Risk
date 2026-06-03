"""
Stage 2: Synthetic vessel call generator.

Generates ~50,000 vessel call records (2020-2024, 60 ports) with realistic
delay distributions calibrated to real anchor data.

Methodology:
  - Base delay: log-normal distribution parameterised by annual CPPI score
  - GPR shocks: multiplier based on monthly Caldara-Iacoviello GPR index
  - Hard-coded shocks: COVID, Suez, US congestion, Red Sea, Panama Canal
  - Weather modulation: real Open-Meteo wave height data

Output: data/processed/vessel_calls_synthetic.csv
"""

import pandas as pd
import numpy as np
import openmeteo_requests
import requests_cache
from retry_requests import retry
from pathlib import Path
from tqdm import tqdm
import uuid
import time

ROOT = Path(__file__).parent.parent
SEED = 42
rng = np.random.default_rng(SEED)

# Calls per year by TEU tier — scaled so total ~50k across 60 ports × 5 years
CALLS_PER_YEAR = {1: 300, 2: 150, 3: 60}

# ---------------------------------------------------------------------------
# SHOCK EVENT DEFINITIONS
# ---------------------------------------------------------------------------
SHOCK_EVENTS = [
    # COVID-19 global disruption
    # Multiplier varies by sub-period; affects all ports
    {
        "name": "covid",
        "periods": [
            ("2020-01-01", "2020-03-31", 1.5,  "all"),   # early spread
            ("2020-04-01", "2020-09-30", 2.5,  "all"),   # peak disruption
            ("2020-10-01", "2021-03-31", 2.0,  "all"),   # ongoing / second wave
            ("2021-04-01", "2021-12-31", 1.7,  "all"),   # gradual recovery
        ],
    },
    # Suez Canal blockage (Ever Given) — 23 Mar to 29 Mar 2021
    # Ripple effects through mid-April in Med/Europe
    {
        "name": "suez",
        "periods": [
            ("2021-03-23", "2021-03-29", 3.0, ["europe", "middle_east"]),
            ("2021-03-30", "2021-04-15", 1.6, ["europe", "middle_east"]),
        ],
    },
    # US West Coast congestion
    {
        "name": "us_congestion",
        "periods": [
            ("2021-10-01", "2022-01-31", 3.8, ["USLAX", "USLGB"]),
            ("2022-02-01", "2022-03-31", 2.5, ["USLAX", "USLGB"]),
        ],
    },
    # Red Sea / Houthi attacks — route diversion to Cape of Good Hope
    {
        "name": "red_sea",
        "periods": [
            ("2023-12-01", "2024-06-30", 2.5, ["EGPSD", "AEJEA", "SGSIN", "OMSLL", "LKCMB"]),
            ("2024-07-01", "2024-12-31", 2.0, ["EGPSD", "AEJEA", "SGSIN", "OMSLL", "LKCMB"]),
        ],
    },
    # Panama Canal drought restrictions
    {
        "name": "panama",
        "periods": [
            ("2023-07-01", "2023-12-31", 1.8, ["PAONX", "MXZLO", "MXLZC"]),
        ],
    },
]

# ---------------------------------------------------------------------------
# WEATHER HELPERS
# ---------------------------------------------------------------------------

def get_openmeteo_client():
    cache = requests_cache.CachedSession(
        str(ROOT / ".cache/openmeteo"), expire_after=-1
    )
    session = retry(cache, retries=5, backoff_factor=0.5)
    return openmeteo_requests.Client(session=session)


def fetch_weather_monthly(port_master: pd.DataFrame) -> pd.DataFrame:
    """
    Fetch monthly max wave height for all 60 ports, 2020-2024.
    Returns DataFrame: (locode, year, month, wave_height_max).
    Caches result to data/weather/weather_monthly.csv.
    """
    cache_file = ROOT / "data/weather/weather_monthly.csv"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        print("  Loaded weather from cache.")
        return pd.read_csv(cache_file)

    print("  Fetching weather from Open-Meteo (one call per port, cached)...")
    client = get_openmeteo_client()
    all_records = []

    for _, port in tqdm(port_master.iterrows(), total=len(port_master), desc="  Weather"):
        try:
            time.sleep(0.6)   # stay under Open-Meteo free-tier rate limit
            params = {
                "latitude":   port.lat,
                "longitude":  port.lon,
                "daily":      ["wave_height_max"],
                "start_date": "2020-01-01",
                "end_date":   "2024-12-31",
            }
            r = client.weather_api(
                "https://marine-api.open-meteo.com/v1/marine", params=params
            )
            daily = r[0].Daily()
            dates  = pd.date_range(start="2020-01-01", end="2024-12-31", freq="D")
            waves  = daily.Variables(0).ValuesAsNumpy()

            df_d = pd.DataFrame({"date": dates, "wave": waves})
            df_d["year"]  = df_d.date.dt.year
            df_d["month"] = df_d.date.dt.month

            monthly = (
                df_d.groupby(["year", "month"])
                .agg(wave_height_max=("wave", "max"))
                .reset_index()
            )
            monthly.insert(0, "locode", port.locode)
            all_records.append(monthly)

        except Exception as e:
            print(f"    Warning: weather fetch failed for {port.locode}: {e}")
            # Fill with zeros (no weather delay) for this port
            for year in range(2020, 2025):
                for month in range(1, 13):
                    all_records.append(pd.DataFrame([{
                        "locode": port.locode, "year": year,
                        "month": month, "wave_height_max": 0.0
                    }]))

    df_weather = pd.concat(all_records, ignore_index=True)
    df_weather["wave_height_max"] = df_weather["wave_height_max"].fillna(0.0)
    df_weather.to_csv(cache_file, index=False)
    print(f"  Weather cached to {cache_file}")
    return df_weather


def weather_multiplier(wave_height_m: float) -> float:
    """Delay multiplier from significant wave height."""
    if wave_height_m is None or np.isnan(wave_height_m) or wave_height_m < 1.5:
        return 1.0
    elif wave_height_m < 2.5:
        return 1.1
    elif wave_height_m < 3.5:
        return 1.3
    else:
        return 1.6


# ---------------------------------------------------------------------------
# CPPI → LOG-NORMAL PARAMETERS
# ---------------------------------------------------------------------------

def cppi_to_lognormal(cppi_score) -> tuple:
    """
    Map annual CPPI score to log-normal delay distribution parameters.

    CPPI scores in the World Bank annex: positive = good, negative = poor.
    Thresholds calibrated against published CPPI tier descriptions.
    Returns (mu, sigma) for numpy.lognormal(mu, sigma).
    """
    if cppi_score is None or np.isnan(float(cppi_score)):
        cppi_score = 0   # treat unknown as average

    cppi_score = float(cppi_score)

    if cppi_score > 100:          # top tier: very efficient (Singapore, Yangshan)
        mean_d, std_d = 0.5, 0.8
    elif cppi_score > 50:         # above average
        mean_d, std_d = 1.2, 1.5
    elif cppi_score >= 0:         # average
        mean_d, std_d = 2.5, 2.8
    else:                         # below average / poor (Durban, congested US ports)
        mean_d, std_d = 4.5, 4.2

    # Convert mean/std → log-normal mu/sigma
    sigma2 = np.log(1 + (std_d / mean_d) ** 2)
    mu     = np.log(mean_d) - sigma2 / 2
    return mu, np.sqrt(sigma2)


def p_on_time(cppi_score) -> float:
    """
    Base probability that a vessel call has zero delay, by CPPI tier.
    Calibrated with global GPR driving multipliers; overall delay rate lands ~33-37%.
    """
    cppi_score = float(cppi_score) if cppi_score is not None else 0
    if cppi_score > 100:
        return 0.85
    elif cppi_score > 50:
        return 0.78
    elif cppi_score >= 0:
        return 0.70
    else:
        return 0.58


# ---------------------------------------------------------------------------
# SHOCK EVENT LOOKUP
# ---------------------------------------------------------------------------

def build_shock_lookup():
    """
    Pre-build a lookup dict: (locode, year, month) → (shock_name, multiplier).
    A call can only be under one shock (highest multiplier wins).
    """
    lookup = {}
    port_master = pd.read_csv(ROOT / "data/processed/port_master.csv")
    all_locodes = set(port_master["locode"])
    region_map  = dict(zip(port_master["locode"], port_master["region"]))

    for event in SHOCK_EVENTS:
        for (start_str, end_str, mult, scope) in event["periods"]:
            start = pd.Timestamp(start_str)
            end   = pd.Timestamp(end_str)

            for locode in all_locodes:
                # Determine if this port is in scope
                if scope == "all":
                    in_scope = True
                elif isinstance(scope, list):
                    # Could be list of locodes or list of regions
                    if locode in scope:
                        in_scope = True
                    else:
                        region = region_map.get(locode, "")
                        in_scope = region in scope
                else:
                    in_scope = False

                if not in_scope:
                    continue

                # Mark each (locode, year, month) in the date range
                current = start.replace(day=1)
                while current <= end:
                    key = (locode, current.year, current.month)
                    existing = lookup.get(key, (None, 1.0))
                    if mult > existing[1]:
                        lookup[key] = (event["name"], mult)
                    current += pd.DateOffset(months=1)

    return lookup


# ---------------------------------------------------------------------------
# GPR MULTIPLIER
# ---------------------------------------------------------------------------

def gpr_multiplier(gpr_value: float) -> float:
    """Delay multiplier from monthly GPR index (baseline 100)."""
    if gpr_value is None or np.isnan(gpr_value):
        return 1.0
    if gpr_value < 100:
        return 1.0
    elif gpr_value < 150:
        return 1.3
    elif gpr_value < 200:
        return 1.8
    else:
        return 2.5


# ---------------------------------------------------------------------------
# VESSEL CHARACTERISTICS
# ---------------------------------------------------------------------------

VESSEL_TYPE_PROBS = [0.80, 0.10, 0.10]  # container, bulk, tanker
VESSEL_TYPES = ["container", "bulk", "tanker"]

VESSEL_SIZE_PARAMS = {
    # (min_teu, max_teu) for container calls per tier
    1: (5000, 24000),
    2: (2000, 10000),
    3: (500,  4000),
}


def draw_vessel(teu_tier: int, rng: np.random.Generator) -> tuple:
    v_type = rng.choice(VESSEL_TYPES, p=VESSEL_TYPE_PROBS)
    lo, hi = VESSEL_SIZE_PARAMS[teu_tier]
    if v_type == "container":
        size = int(rng.integers(lo, hi))
    else:
        size = int(rng.integers(500, 3000))  # bulk/tanker: smaller TEU equivalent
    return v_type, size


def scheduled_port_hours(cppi_score: float, vessel_size_teu: int) -> float:
    """
    Approximate scheduled port time based on CPPI tier and vessel size.
    Efficient ports + smaller vessels → faster turnaround.
    """
    cppi_score = float(cppi_score) if cppi_score is not None else 0
    if cppi_score > 100:
        base_h = 24
    elif cppi_score > 50:
        base_h = 36
    elif cppi_score >= 0:
        base_h = 48
    else:
        base_h = 72

    # Scale slightly with vessel size
    size_factor = 1 + (vessel_size_teu - 5000) / 100000
    size_factor = max(0.8, min(size_factor, 1.5))
    return round(base_h * size_factor, 1)


# ---------------------------------------------------------------------------
# DELAY CAUSE ASSIGNMENT
# ---------------------------------------------------------------------------

def assign_cause(shock_name: str, w_mult: float, cppi_score: float) -> str:
    if shock_name in ("red_sea", "suez"):
        return "geopolitical"
    if shock_name in ("us_congestion", "covid"):
        return "congestion"
    if shock_name == "panama":
        return "operational"
    if w_mult > 1.1:
        return "weather"
    if float(cppi_score) < 0:
        return "congestion"
    return "operational"


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------

def generate():
    print("=== Stage 2: Synthetic Vessel Call Generator ===\n")

    # Load anchor data
    port_master = pd.read_csv(ROOT / "data/processed/port_master.csv")
    gpr_df      = pd.read_csv(ROOT / "data/processed/gpr_monthly.csv",
                               parse_dates=["date"])

    # Global GPR lookup: (year, month) -> gpr_global
    gpr_global_lookup = {
        (int(r.year), int(r.month)): r.gpr_global
        for _, r in gpr_df.iterrows()
    }

    # Country-specific GPR lookup: (col_name, year, month) -> gpr_country_value
    country_cols = [c for c in gpr_df.columns if c.startswith("GPRHC_")]
    gpr_country_lookup = {}
    for _, r in gpr_df.iterrows():
        for col in country_cols:
            val = getattr(r, col)
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                gpr_country_lookup[(col, int(r.year), int(r.month))] = float(val)

    # Build shock lookup
    print("Building shock event lookup...")
    shock_lookup = build_shock_lookup()

    # Fetch / load weather
    print("Loading weather data...")
    weather_df  = fetch_weather_monthly(port_master)
    weather_lkp = {
        (r.locode, int(r.year), int(r.month)): r.wave_height_max
        for _, r in weather_df.iterrows()
    }

    # Generate records
    records = []
    years   = list(range(2020, 2025))

    for _, port in tqdm(port_master.iterrows(), total=len(port_master), desc="Generating"):
        locode  = port.locode
        tier    = int(port.teu_tier)
        calls_per_yr = CALLS_PER_YEAR[tier]

        # CPPI score per year
        cppi_by_year = {
            2020: port.cppi_2020,
            2021: port.cppi_2021,
            2022: port.cppi_2022,
            2023: port.cppi_2023,
            2024: port.cppi_2024,
        }

        for year in years:
            cppi = cppi_by_year[year]
            mu_base, sigma_base = cppi_to_lognormal(cppi)
            p_ot = p_on_time(cppi)

            # Spread calls uniformly across the year
            year_start = pd.Timestamp(f"{year}-01-01")
            year_end   = pd.Timestamp(f"{year}-12-31")
            n_days     = (year_end - year_start).days + 1
            day_offsets = rng.integers(0, n_days, size=calls_per_yr)

            for day_off in day_offsets:
                arrival = year_start + pd.Timedelta(days=int(day_off))
                month   = arrival.month

                # --- GPR: global index (always available) ---
                gpr_global = gpr_global_lookup.get((year, month), 100.0)

                # --- GPR: country-specific where available, else fall back to global ---
                gpr_col = port.gpr_col if pd.notna(port.gpr_col) else None
                if gpr_col:
                    gpr_country = gpr_country_lookup.get((gpr_col, year, month), gpr_global)
                else:
                    gpr_country = gpr_global

                # Global GPR drives the delay multiplier — it is on the correct 50-320 scale.
                # Country share (fractional 0-2 scale) is stored as a separate ML feature
                # but NOT used for the multiplier (different scale; thresholds would never fire).
                gpr_val  = gpr_global
                gpr_mult = gpr_multiplier(gpr_val)
                gpr_cat  = (
                    "low"     if gpr_val < 100 else
                    "medium"  if gpr_val < 150 else
                    "high"    if gpr_val < 200 else
                    "extreme"
                )

                # --- Shock event multiplier ---
                shock_name, s_mult = shock_lookup.get((locode, year, month), (None, 1.0))

                # --- Weather multiplier ---
                wave_h   = weather_lkp.get((locode, year, month), 0.0)
                w_mult   = weather_multiplier(wave_h)

                # --- Combined multiplier (multiplicative) ---
                combined = gpr_mult * s_mult * w_mult

                # --- On-time probability (shock reduces it linearly) ---
                # Additive reduction: each unit of combined above 1.0 subtracts 0.12 from p_on_time
                # This is softer than dividing and keeps rates more calibrated.
                adj_p_ot = p_ot - 0.12 * (combined - 1.0)
                adj_p_ot = max(0.05, min(adj_p_ot, 0.92))

                # --- Draw delay ---
                if rng.random() < adj_p_ot:
                    delay_d = 0.0
                else:
                    # Scale lognormal mean by combined multiplier
                    mean_d = np.exp(mu_base + sigma_base ** 2 / 2) * combined
                    std_d  = mean_d * 1.1  # keep CV ~1.1
                    sigma2 = np.log(1 + (std_d / mean_d) ** 2)
                    mu_adj = np.log(mean_d) - sigma2 / 2
                    delay_d = float(rng.lognormal(mu_adj, np.sqrt(sigma2)))
                    delay_d = max(0.5, delay_d)

                # --- Vessel characteristics ---
                v_type, v_size = draw_vessel(tier, rng)

                # --- Port hours ---
                sched_h  = scheduled_port_hours(cppi, v_size)
                actual_h = sched_h + delay_d * 24

                # --- Delay cause ---
                cause = assign_cause(shock_name, w_mult, cppi)

                records.append({
                    "vessel_call_id":        str(uuid.uuid4())[:12],
                    "port_code":             locode,
                    "port_name":             port.port_name,
                    "port_country":          port.country,
                    "port_lat":              port.lat,
                    "port_lon":              port.lon,
                    "arrival_date":          arrival.date(),
                    "year":                  year,
                    "month":                 month,
                    "quarter":               (month - 1) // 3 + 1,
                    "vessel_type":           v_type,
                    "vessel_size_teu":       v_size,
                    "scheduled_port_hours":  sched_h,
                    "actual_port_hours":     round(actual_h, 1),
                    "delay_days":            round(delay_d, 3),
                    "is_delayed":            int(delay_d > 0.5),
                    "delay_cause":           cause if delay_d > 0.5 else "none",
                    "cppi_score":            round(float(cppi), 1) if cppi is not None else None,
                    "gpr_index":             round(gpr_global, 1),
                    "gpr_country_share":     round(gpr_country, 4),  # GPRHC fractional (0-2 scale), ML feature only
                    "gpr_category":          gpr_cat,
                    "wave_height_m":         round(float(wave_h), 2),
                    "shock_event":           shock_name if shock_name else "none",
                    "shock_multiplier":      round(s_mult, 2),
                    "gpr_multiplier":        round(gpr_mult, 2),
                    "weather_multiplier":    round(w_mult, 2),
                    "combined_multiplier":   round(combined, 2),
                    "base_delay_mean":       round(np.exp(mu_base + sigma_base ** 2 / 2), 2),
                    "lpi_score":             port.lpi_score,
                    "lsci_score":            port.lsci_score,
                    "region":                port.region,
                })

    df = pd.DataFrame(records)
    out = ROOT / "data/processed/vessel_calls_synthetic.csv"
    df.to_csv(out, index=False)
    print(f"\nGenerated {len(df):,} records -> {out}")
    return df


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def validate(df: pd.DataFrame) -> bool:
    print("\n=== VALIDATION CHECKS ===\n")
    passed = True

    # 1. Overall delay rate
    rate = df["is_delayed"].mean()
    ok   = 0.30 <= rate <= 0.50
    print(f"[{'PASS' if ok else 'FAIL'}] Overall delay rate: {rate:.1%}  (target 35-40%, tolerance 30-50%)")
    if not ok: passed = False

    # 2. LA/LB congestion spike Oct 2021 – Mar 2022
    la_shock = df[
        (df["port_code"].isin(["USLAX", "USLGB"])) &
        (((df["year"] == 2021) & (df["month"] >= 10)) |
         ((df["year"] == 2022) & (df["month"] <= 3)))
    ]
    la_pre = df[
        (df["port_code"].isin(["USLAX", "USLGB"])) &
        (df["year"] == 2020)
    ]
    if len(la_shock) > 0 and len(la_pre) > 0:
        shock_mean = la_shock["delay_days"].mean()
        pre_mean   = la_pre["delay_days"].mean()
        ratio      = shock_mean / max(pre_mean, 0.01)
        ok         = ratio > 2.0
        print(f"[{'PASS' if ok else 'FAIL'}] LA/LB congestion spike: "
              f"{shock_mean:.2f}d vs pre-shock {pre_mean:.2f}d (ratio {ratio:.1f}x, need >2x)")
        if not ok: passed = False
    else:
        print("[SKIP] LA/LB congestion check — insufficient data")

    # 3. Red Sea ports spike Dec 2023+
    red_sea_ports = ["EGPSD", "AEJEA", "SGSIN", "OMSLL"]
    rs_shock = df[
        (df["port_code"].isin(red_sea_ports)) &
        (df["year"] == 2024)
    ]
    rs_pre = df[
        (df["port_code"].isin(red_sea_ports)) &
        (df["year"] == 2022)
    ]
    if len(rs_shock) > 0 and len(rs_pre) > 0:
        shock_mean = rs_shock["delay_days"].mean()
        pre_mean   = rs_pre["delay_days"].mean()
        ratio      = shock_mean / max(pre_mean, 0.01)
        ok         = ratio > 1.5
        print(f"[{'PASS' if ok else 'FAIL'}] Red Sea spike: "
              f"{shock_mean:.2f}d vs pre-shock {pre_mean:.2f}d (ratio {ratio:.1f}x, need >1.5x)")
        if not ok: passed = False
    else:
        print("[SKIP] Red Sea check — insufficient data")

    # 4. COVID period delay elevation (2021 vs 2019-equivalent baseline)
    covid_peak = df[(df["year"] == 2021)]
    post_covid = df[(df["year"] == 2024)]
    if len(covid_peak) > 0 and len(post_covid) > 0:
        c_rate  = covid_peak["is_delayed"].mean()
        pc_rate = post_covid["is_delayed"].mean()
        ok      = c_rate > pc_rate
        print(f"[{'PASS' if ok else 'FAIL'}] COVID elevation: "
              f"2021 delay rate {c_rate:.1%} vs 2024 {pc_rate:.1%}")
        if not ok: passed = False

    # 5. Efficient ports have lower delay than poor ports
    good = df[df["cppi_score"] > 100]["delay_days"].mean()
    poor = df[df["cppi_score"] < 0]["delay_days"].mean()
    ok   = poor > good * 1.5
    print(f"[{'PASS' if ok else 'FAIL'}] CPPI correlation: "
          f"good-port mean delay {good:.2f}d vs poor-port {poor:.2f}d")
    if not ok: passed = False

    # 6. Summary stats
    print(f"\nDataset summary:")
    print(f"  Total records:        {len(df):,}")
    print(f"  Delayed records:      {df['is_delayed'].sum():,} ({df['is_delayed'].mean():.1%})")
    print(f"  Date range:           {df['arrival_date'].min()} to {df['arrival_date'].max()}")
    print(f"  Mean delay (all):     {df['delay_days'].mean():.2f} days")
    print(f"  Mean delay (delayed): {df[df['is_delayed']==1]['delay_days'].mean():.2f} days")
    print(f"\nDelay rate by year:")
    by_year = df.groupby("year")["is_delayed"].mean()
    print(by_year.to_string())
    print(f"\nDelay rate by shock event:")
    by_shock = df.groupby("shock_event")["is_delayed"].mean().sort_values(ascending=False)
    print(by_shock.to_string())

    print(f"\n{'ALL CHECKS PASSED' if passed else 'SOME CHECKS FAILED — review parameters'}")
    return passed


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = generate()
    ok = validate(df)
    if not ok:
        print("\nWARNING: Validation failed. Review parameters before proceeding to Stage 3.")
