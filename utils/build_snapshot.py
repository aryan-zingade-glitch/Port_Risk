"""
Bake a static snapshot of the map's data into the frontend bundle.

The dashboard's underlying data is historical (2020-2024) and never changes, so
the World Risk Map has no reason to wait on a live API to draw itself. This
script pulls every month of risk scores once and writes them to
dashboard/public/snapshot.json, which Vercel serves from its CDN. The map paints
from that instantly; the API is then only needed for port drilldowns and route
simulation.

Re-run whenever the model is retrained:
    python utils/build_snapshot.py
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = sys.argv[1] if len(sys.argv) > 1 else "https://nautiq-api.onrender.com"
OUT = Path(__file__).parent.parent / "dashboard/public/snapshot.json"

YEARS = range(2020, 2025)
MONTHS = range(1, 13)

# Only the fields the map reads — see WorldRiskMap getPortRisk/tooltip.
PORT_FIELDS = ("locode", "port_name", "country", "lat", "lon", "region",
               "teu_tier", "risk_score", "risk_label", "delay_prob",
               "delay_days_pred")
RISK_FIELDS = ("risk_score", "risk_label", "delay_prob", "delay_days_pred")


def get(path):
    # The API sleeps when idle, so the first call may need to cold-boot it.
    r = requests.get(f"{API}{path}", timeout=120)
    r.raise_for_status()
    return r.json()


def fetch_month(ym):
    year, month = ym
    rows = get(f"/risk-scores/{year}/{month}")
    # Key by locode and drop the redundant port_name; the ports list carries it.
    return f"{year}-{month}", {
        r["locode"]: {k: r[k] for k in RISK_FIELDS if k in r} for r in rows
    }


def main():
    print(f"source: {API}")
    ports = [{k: p[k] for k in PORT_FIELDS if k in p} for p in get("/ports")]
    print(f"ports: {len(ports)}")

    months = [(y, m) for y in YEARS for m in MONTHS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        risk_scores = dict(pool.map(fetch_month, months))
    print(f"months: {len(risk_scores)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ports": ports, "riskScores": risk_scores}
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
