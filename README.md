# NautIQ — Global Port Delay Intelligence

A production-grade port delay prediction system built as a flagship data science portfolio project.
Predicts vessel call delays at 60 major container ports worldwide using public data and a calibrated
synthetic generator — mirroring the problem Maersk's PortSight platform solves commercially.

**Live demo:** _[Vercel URL — add after deployment]_  
**API docs:** _[Render URL — add after deployment]_`/docs`

---

## The Problem

Enterprise port congestion data costs $500–$1,000/month from providers like Portcast and Kpler.
I built a calibrated synthetic generator anchored to three real public datasets and trained ML models
on the output — demonstrating that principled data engineering can substitute for expensive commercial
feeds, and that solving the data problem is often more valuable than the modelling itself.

---

## Architecture

```
Real anchor data          Synthetic generator        ML models            React dashboard
─────────────────         ───────────────────        ─────────────        ─────────────────
World Bank CPPI     ──►   51,150 vessel call  ──►    XGBoost              NautIQ (MapLibre)
GPR Index           ──►   records (2020-2024)        LightGBM       ──►   World Risk Map
Open-Meteo weather  ──►   60 ports, 30 cols   ──►    SHAP               ╠ Port Drilldown
                                                      Risk scores        ╚ Route Simulator
                                                            │
                                                      FastAPI ──► REST JSON
```

---

## Data Sources

| Source | What it provides | License |
|--------|-----------------|---------|
| **World Bank CPPI 2020–2024** | Port efficiency scores for 403 ports | CC BY 3.0 IGO |
| **Caldara-Iacoviello GPR Index** | Monthly geopolitical risk, 44 countries | Free (Fed working paper) |
| **Open-Meteo Marine API** | Daily wave height at any lat/lon, 1980–present | Free, no key |
| **World Bank LPI 2018** | Country-level logistics quality, 139 countries | Open data |

### Why Synthetic Data?

Real per-vessel delay records (Portcast, Kpler, MarineTraffic) cost $500–$1,000/month — inaccessible
for a student project. Instead I built a calibrated synthetic generator with documented assumptions:

- **Base delay distribution**: log-normal, parameterised by each port's annual CPPI score
- **GPR shock injection**: multiplier based on monthly Caldara-Iacoviello index (1.0–2.5×)
- **Five hard-coded shock events** (COVID-19, Suez blockage, US West Coast congestion,
  Red Sea/Houthi crisis, Panama Canal drought) with real date ranges and affected ports
- **Weather modulation**: real Open-Meteo wave height → delay multiplier (1.0–1.6×)

**Validation checks (all passed):**
- Overall delay rate: 33.1% (target 30–50%, consistent with published 65% schedule reliability)
- LA/LB congestion spike (Oct 2021–Mar 2022): 11.1× vs pre-shock baseline
- Red Sea ports spike (Dec 2023+): 9.2× vs pre-shock baseline
- COVID 2021 elevation confirmed; CPPI correlation confirmed

The generator is fully open-sourced — every assumption is documented and auditable in
[`generator/generate_vessel_calls.py`](generator/generate_vessel_calls.py).

---

## ML Architecture

### Model 1 — XGBoost Classifier (Target A: will this call be delayed?)

| Metric | Value |
|--------|-------|
| AUC (2024 test set) | 0.68 |
| F1 | 0.54 |
| Features | 24 |
| Temporal split | Train 2020–2022 · Val 2023 · Test 2024 |

**Why AUC 0.68 is the realistic ceiling for this feature set:**  
The strongest predictor of delays is which shock event was active — but that label is excluded as
leakage (you don't know at inference time whether a vessel will encounter a Houthi attack).
On the 2024 test set, the mean GPR index differs by only 2.7 points between delayed and on-time
calls, making the classes nearly indistinguishable from features alone. A production system with
real AIS data and vessel-tracking feeds would have access to live port queue depth and anchorage
counts — the features that would push AUC above 0.85.

### Model 2 — LightGBM Regressor (Target B: how many days?)

Trained on delayed calls only (log-transformed target).

| Metric | Value |
|--------|-------|
| RMSE | 6.82 days |
| **Median Absolute Error** | **1.6 days** |
| Train / test split | Same as Model 1 |

RMSE is dominated by Red Sea rerouting events (Cape of Good Hope bypass adds ~14 days).
Median AE of 1.6 days is more representative of typical prediction accuracy.

### Model 3 — Port Risk Score (Target C: 0–100 risk score per port-month)

Not a separate ML model — a weighted combination:

```
risk_score = 0.40 × P(delayed) + 0.30 × normalised_E[delay] + 0.15 × GPR + 0.10 × wave + 0.05 × shock_flag
```

Normalised 0–100 across all 3,600 port-month combinations. Green < 34, Amber 34–66, Red > 66.

### Key Features (by SHAP importance)

1. `cppi_score_clipped` — port efficiency (World Bank)
2. `gpr_index` — global geopolitical risk (Caldara-Iacoviello)
3. `port_mean_delay_lag6m` — trailing 6-month average delay magnitude
4. `port_mean_delay_lag3m` — trailing 3-month average delay magnitude
5. `wave_height_m` — significant wave height (Open-Meteo)

### Why XGBoost + LightGBM?

XGBoost: tabular data, handles mixed types, SHAP-native, outperforms Random Forest at this scale.  
LightGBM: faster on larger datasets, better at sparse features, handles 0-inflated target distribution.  
No neural network: dataset is 51k rows — tabular structure, interpretability needed for interviews.

---

## API Endpoints

The FastAPI backend serves all model outputs via REST JSON. Docs available at `/docs`.

| Endpoint | Description |
|----------|-------------|
| `GET /ports` | All 60 ports with current risk scores |
| `GET /ports/{port_code}` | Port detail + 12-month history + SHAP waterfall |
| `GET /risk-scores/{year}/{month}` | All port risk scores for a given month |
| `GET /route/{origin}/{dest}` | Route risk (Suez/Panama/Atlantic waypoint routing) |

All data loaded at startup. Latencies: 21–259 ms per endpoint.

---

## Dashboard (NautIQ)

Three panels:

**Panel 1 — World Risk Map**  
MapLibre GL dark map. 60 port circles: colour = risk score, size = TEU tier.
Time slider scrubs 2020–2024 with shock event annotations. Click any port → Port Drilldown.

**Panel 2 — Port Drilldown**  
12-month delay rate history (bar chart), SHAP waterfall (top-8 features), risk metrics, port metadata.

**Panel 3 — Route Simulator**  
Select origin + destination. Route drawn through correct geographic waypoints
(Suez Canal for Asia↔Europe; Panama Canal for Asia↔Americas). Segment risk breakdown,
cumulative delay probability, expected total delay days.

---

## How to Run Locally

```bash
# Clone
git clone https://github.com/aryan-zingade-glitch/Port_Risk.git
cd Port_Risk

# Python environment
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# API (port 8000)
uvicorn api.main:app --port 8000

# Dashboard (port 5173) — separate terminal
cd dashboard
npm install
npm run dev
# Open http://localhost:5173
```

---

## Project Structure

```
port_risk/
├── api/                    FastAPI backend
│   └── main.py
├── context/                Project master document
├── data/
│   └── processed/          Cleaned CSVs (committed)
├── dashboard/              NautIQ React app (Vite + Tailwind + MapLibre)
├── generator/              Synthetic data generator + port master builder
├── models/                 Trained models (.pkl), SHAP outputs, results
├── utils/                  Helper scripts (GPR parser, CPPI parser)
├── requirements.txt        Python dependencies
└── README.md
```

---

## What Would Make This Better With Real Data

With access to Kpler or MarineTraffic historical AIS data (~$500–1,000/month):
- Replace synthetic vessel calls with real port call events
- Add live vessel queue depth and anchorage count features (AUC expected: 0.85+)
- Add satellite imagery-based congestion detection (used in Maersk Star Connect)

The synthetic data schema exactly mirrors what real AIS data would provide — the architecture
is already designed for this upgrade.

---

## Attribution

- World Bank CPPI: [openknowledge.worldbank.org](https://openknowledge.worldbank.org/entities/publication/fa57ba78-0402-4eb4-b168-51708cf526f7) · CC BY 3.0 IGO
- GPR Index: Caldara & Iacoviello (2022), *American Economic Review* 112(4): 1194–1225 · [matteoiacoviello.com/gpr.htm](https://www.matteoiacoviello.com/gpr.htm)
- Open-Meteo: [open-meteo.com](https://open-meteo.com) · CC BY 4.0
- World Bank LPI: [lpi.worldbank.org](https://lpi.worldbank.org) · Open Data

---

*Built by Aryan Zingade · Final year B.Tech CS + Data Science, Manipal University Bangalore*
