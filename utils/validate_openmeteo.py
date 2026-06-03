"""
Stage 1 checkpoint: test Open-Meteo marine API for all 60 ports.
Confirms wave_height, wind_speed, sea_surface_temp are available 2020-2024.

Fetches a 7-day sample (2022-01-01 to 2022-01-07) per port to verify coverage.
Results are printed; failures are flagged.
"""

import pandas as pd
import openmeteo_requests
import requests_cache
from retry_requests import retry
from pathlib import Path
import time

ROOT = Path(__file__).parent.parent


def get_client():
    cache = requests_cache.CachedSession(str(ROOT / ".cache/openmeteo"), expire_after=-1)
    session = retry(cache, retries=3, backoff_factor=0.5)
    return openmeteo_requests.Client(session=session)


def test_port(client, locode, name, lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ["wave_height_max", "wind_speed_10m_max", "sea_surface_temperature_mean"],
        "start_date": "2022-01-01",
        "end_date": "2022-01-07",
    }
    try:
        resp = client.weather_api("https://marine-api.open-meteo.com/v1/marine", params=params)
        daily = resp[0].Daily()
        wave = daily.Variables(0).ValuesAsNumpy()
        wind = daily.Variables(1).ValuesAsNumpy()
        sst  = daily.Variables(2).ValuesAsNumpy()
        wave_ok = any(v == v for v in wave)  # not all NaN
        return {"locode": locode, "name": name, "wave_ok": wave_ok,
                "wave_sample": round(float(wave[0]), 2) if wave_ok else None,
                "wind_sample": round(float(wind[0]), 2) if any(v == v for v in wind) else None,
                "sst_sample":  round(float(sst[0]),  2) if any(v == v for v in sst)  else None,
                "status": "OK"}
    except Exception as e:
        return {"locode": locode, "name": name, "status": f"ERROR: {e}"}


def validate_all():
    port_master = pd.read_csv(ROOT / "data/processed/port_master.csv")
    client = get_client()

    results = []
    for _, row in port_master.iterrows():
        r = test_port(client, row["locode"], row["port_name"], row["lat"], row["lon"])
        results.append(r)
        status = r["status"]
        wave = r.get("wave_sample", "-")
        print(f"  {row['locode']:7s} {row['port_name']:25s} {status}  wave={wave}")

    df = pd.DataFrame(results)
    errors = df[df["status"].str.startswith("ERROR")]
    ok = df[df["status"] == "OK"]

    print(f"\n=== OPEN-METEO VALIDATION ===")
    print(f"Ports OK:     {len(ok)}/60")
    print(f"Ports failed: {len(errors)}/60")
    if not errors.empty:
        print("FAILURES:")
        print(errors[["locode", "name", "status"]].to_string())

    return df


if __name__ == "__main__":
    validate_all()
