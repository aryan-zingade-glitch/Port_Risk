"""
Stage 4: FastAPI Backend — PortRisk API

Endpoints:
  GET /health
  GET /ports                        → all 60 ports with current risk scores
  GET /ports/{port_code}            → port detail + 12m history + SHAP waterfall
  GET /risk-scores/{year}/{month}   → all port risk scores for a given month
  GET /route/{origin}/{dest}        → route risk analysis between two ports

All data and models are loaded once at startup.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import numpy as np
import joblib
import json
from pathlib import Path

# ---------------------------------------------------------------------------
ROOT      = Path(__file__).parent.parent
PROCESSED = ROOT / "data/processed"
MODELS    = ROOT / "models"

app = FastAPI(
    title="PortRisk API",
    description="Global port delay intelligence — PortRisk",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# STARTUP: load everything once
# ---------------------------------------------------------------------------

_data: dict = {}

@app.on_event("startup")
def load_data():
    print("Loading data and models...")

    _data["port_master"] = pd.read_csv(PROCESSED / "port_master.csv")
    _data["risk_scores"] = pd.read_csv(PROCESSED / "port_risk_scores.csv")
    _data["vessel_calls"] = pd.read_csv(
        PROCESSED / "vessel_calls_synthetic.csv",
        parse_dates=["arrival_date"],
    )
    _data["shap_clf"] = pd.read_csv(PROCESSED / "shap_classifier.csv")
    _data["gpr"]      = pd.read_csv(PROCESSED / "gpr_monthly.csv", parse_dates=["date"])

    _data["clf"] = joblib.load(MODELS / "xgb_classifier.pkl")
    _data["reg"] = joblib.load(MODELS / "lgbm_regressor.pkl")

    # Pre-compute: most recent risk score per port (latest year/month in data)
    rs = _data["risk_scores"]
    latest_ym = rs[["year", "month"]].apply(lambda r: r.year * 12 + r.month, axis=1)
    latest_idx = rs.groupby("locode").apply(lambda g: (g.year * 12 + g.month).idxmax())
    _data["latest_risk"] = rs.loc[latest_idx.values].set_index("locode")

    print(f"  Loaded {len(_data['port_master'])} ports, "
          f"{len(_data['risk_scores'])} risk-score rows, "
          f"{len(_data['vessel_calls'])} vessel calls.")


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _port_row(port_code: str) -> pd.Series:
    pm = _data["port_master"]
    rows = pm[pm["locode"] == port_code.upper()]
    if rows.empty:
        raise HTTPException(status_code=404, detail=f"Port {port_code} not found")
    return rows.iloc[0]


def _risk_row(port_code: str) -> dict:
    try:
        r = _data["latest_risk"].loc[port_code.upper()]
        return {
            "risk_score":      float(r.risk_score),
            "risk_label":      str(r.risk_label),
            "delay_prob":      float(r.delay_prob),
            "delay_days_pred": float(r.delay_days_pred),
        }
    except KeyError:
        return {"risk_score": 0.0, "risk_label": "green", "delay_prob": 0.0, "delay_days_pred": 0.0}


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

# Pre-defined shipping lanes (intermediate waypoints for major route pairs)
_SUEZ_WAYPOINTS   = ["LKCMB", "OMSLL", "EGPSD"]          # Asia → Europe via Suez
_PANAMA_WAYPOINTS = ["PAONX"]                              # Americas ↔ Asia via Panama

def _route_waypoints(origin: str, dest: str) -> list[str]:
    """Return intermediate port codes for a given origin/destination pair."""
    pm   = _data["port_master"].set_index("locode")
    try:
        o_region = pm.loc[origin, "region"]
        d_region = pm.loc[dest,   "region"]
    except KeyError:
        return []

    # Same region → direct (no intermediate waypoints in our port set)
    if o_region == d_region:
        return []

    pair = frozenset([o_region, d_region])

    if "asia_pacific" in pair and "europe" in pair:
        return _SUEZ_WAYPOINTS    # route through Suez Canal zone

    if "asia_pacific" in pair and "americas" in pair:
        return _PANAMA_WAYPOINTS  # route through Panama Canal

    if "europe" in pair and "americas" in pair:
        return []                  # direct Atlantic crossing

    if "middle_east" in pair and "europe" in pair:
        return ["EGPSD"]           # via Suez / Port Said

    if "middle_east" in pair and "asia_pacific" in pair:
        return []

    return []


# ---------------------------------------------------------------------------
# RESPONSE SCHEMAS
# ---------------------------------------------------------------------------

class PortSummary(BaseModel):
    locode: str
    port_name: str
    country: str
    lat: float
    lon: float
    region: str
    teu_tier: int
    risk_score: float
    risk_label: str
    delay_prob: float
    delay_days_pred: float


class MonthlyHistory(BaseModel):
    year: int
    month: int
    delay_rate: float
    mean_delay_days: float
    risk_score: Optional[float]


class ShapEntry(BaseModel):
    feature: str
    shap_value: float
    feature_value: Optional[float]


class PortDetail(BaseModel):
    locode: str
    port_name: str
    country: str
    lat: float
    lon: float
    region: str
    teu_tier: int
    cppi_2024: Optional[float]
    lpi_score: float
    lsci_score: float
    current_risk: dict
    history_12m: list[MonthlyHistory]
    shap_waterfall: list[ShapEntry]


class RiskScoreEntry(BaseModel):
    locode: str
    port_name: str
    risk_score: float
    risk_label: str
    delay_prob: float
    delay_days_pred: float


class RouteSegment(BaseModel):
    from_port: str
    from_name: str
    to_port: str
    to_name: str
    risk_score: float
    risk_label: str
    delay_prob: float


class RouteRisk(BaseModel):
    origin: str
    origin_name: str
    destination: str
    destination_name: str
    waypoints: list[str]
    waypoint_names: list[str]
    all_ports: list[str]
    segments: list[RouteSegment]
    route_risk_score: float
    route_risk_label: str
    cumulative_delay_prob: float
    expected_total_delay_days: float


# ---------------------------------------------------------------------------
# ENDPOINT: health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "ports_loaded": len(_data.get("port_master", [])),
        "risk_scores_loaded": len(_data.get("risk_scores", [])),
    }


# ---------------------------------------------------------------------------
# ENDPOINT: GET /ports
# ---------------------------------------------------------------------------

@app.get("/ports", response_model=list[PortSummary])
def get_ports():
    """All 60 ports with their latest risk score."""
    pm  = _data["port_master"]
    out = []
    for _, row in pm.iterrows():
        risk = _risk_row(row.locode)
        out.append(PortSummary(
            locode          = row.locode,
            port_name       = row.port_name,
            country         = row.country,
            lat             = float(row.lat),
            lon             = float(row.lon),
            region          = row.region,
            teu_tier        = int(row.teu_tier),
            risk_score      = risk["risk_score"],
            risk_label      = risk["risk_label"],
            delay_prob      = risk["delay_prob"],
            delay_days_pred = risk["delay_days_pred"],
        ))
    return out


# ---------------------------------------------------------------------------
# ENDPOINT: GET /ports/{port_code}
# ---------------------------------------------------------------------------

@app.get("/ports/{port_code}", response_model=PortDetail)
def get_port_detail(port_code: str):
    """Port detail: current risk, 12-month history, SHAP waterfall."""
    port = _port_row(port_code)
    lc   = port.locode

    # 12-month history from vessel_calls
    vc = _data["vessel_calls"]
    port_vc = vc[vc["port_code"] == lc].copy()
    port_vc["ym"] = port_vc["year"] * 12 + port_vc["month"]

    # Latest 12 months available
    latest_ym = int(port_vc["ym"].max()) if not port_vc.empty else 2024 * 12 + 12
    min_ym    = latest_ym - 11

    monthly = (
        port_vc[port_vc["ym"] >= min_ym]
        .groupby(["year", "month"])
        .agg(delay_rate=("is_delayed", "mean"), mean_delay_days=("delay_days", "mean"))
        .reset_index()
    )

    # Join risk scores for those months
    rs = _data["risk_scores"]
    port_rs = rs[rs["locode"] == lc][["year", "month", "risk_score"]].copy()
    monthly = monthly.merge(port_rs, on=["year", "month"], how="left")

    history = [
        MonthlyHistory(
            year=int(r.year), month=int(r.month),
            delay_rate=round(float(r.delay_rate), 4),
            mean_delay_days=round(float(r.mean_delay_days), 3),
            risk_score=round(float(r.risk_score), 1) if not pd.isna(r.risk_score) else None,
        )
        for _, r in monthly.sort_values(["year", "month"]).iterrows()
    ]

    # SHAP waterfall — use median SHAP values from the test set for this port
    shap_df   = _data["shap_clf"]
    test_vc   = vc[(vc["port_code"] == lc) & (vc["year"] == 2024)]
    feat_cols = shap_df.columns.tolist()

    if len(test_vc) > 0:
        # Get indices of test records for this port (aligned to shap_df by row position)
        # shap_df has one row per test record (2024 data only)
        test_all  = vc[vc["year"] == 2024].reset_index(drop=True)
        port_idx  = test_all[test_all["port_code"] == lc].index.tolist()
        valid_idx = [i for i in port_idx if i < len(shap_df)]

        if valid_idx:
            shap_vals = shap_df.iloc[valid_idx].mean()
        else:
            shap_vals = shap_df.mean()

        # Feature values: median for this port in 2024
        from models.train_pipeline import engineer_features, get_feature_cols
        import warnings; warnings.filterwarnings("ignore")
        vc_eng    = engineer_features(vc)
        fc        = get_feature_cols(vc_eng)
        port_feats = vc_eng[(vc_eng["port_code"] == lc) & (vc_eng["year"] == 2024)]
        feat_medians = port_feats[fc].median() if len(port_feats) > 0 else pd.Series(dtype=float)
    else:
        shap_vals    = shap_df.mean()
        feat_medians = pd.Series(dtype=float)

    waterfall = []
    for feat in feat_cols:
        sv = float(shap_vals.get(feat, 0))
        fv = float(feat_medians.get(feat, np.nan)) if feat in feat_medians.index else None
        if abs(sv) > 1e-6:
            waterfall.append(ShapEntry(feature=feat, shap_value=round(sv, 5),
                                       feature_value=round(fv, 3) if fv is not None and not np.isnan(fv) else None))

    waterfall.sort(key=lambda x: abs(x.shap_value), reverse=True)

    return PortDetail(
        locode     = lc,
        port_name  = port.port_name,
        country    = port.country,
        lat        = float(port.lat),
        lon        = float(port.lon),
        region     = port.region,
        teu_tier   = int(port.teu_tier),
        cppi_2024  = float(port.cppi_2024) if not pd.isna(port.cppi_2024) else None,
        lpi_score  = float(port.lpi_score),
        lsci_score = float(port.lsci_score),
        current_risk = _risk_row(lc),
        history_12m  = history,
        shap_waterfall = waterfall[:10],   # top 10 features
    )


# ---------------------------------------------------------------------------
# ENDPOINT: GET /risk-scores/{year}/{month}
# ---------------------------------------------------------------------------

@app.get("/risk-scores/{year}/{month}", response_model=list[RiskScoreEntry])
def get_risk_scores(year: int, month: int):
    """All port risk scores for a given year/month (e.g. 2024/3)."""
    rs = _data["risk_scores"]
    pm = _data["port_master"][["locode", "port_name"]].set_index("locode")

    month_rs = rs[(rs["year"] == year) & (rs["month"] == month)]
    if month_rs.empty:
        raise HTTPException(status_code=404,
                            detail=f"No risk scores for {year}-{month:02d}. "
                                   f"Available: 2020-01 to 2024-12.")
    out = []
    for _, r in month_rs.iterrows():
        name = pm.loc[r.locode, "port_name"] if r.locode in pm.index else r.locode
        out.append(RiskScoreEntry(
            locode          = r.locode,
            port_name       = str(name),
            risk_score      = float(r.risk_score),
            risk_label      = str(r.risk_label),
            delay_prob      = float(r.delay_prob),
            delay_days_pred = float(r.delay_days_pred),
        ))
    return sorted(out, key=lambda x: x.risk_score, reverse=True)


# ---------------------------------------------------------------------------
# ENDPOINT: GET /route/{origin}/{dest}
# ---------------------------------------------------------------------------

@app.get("/route/{origin}/{dest}", response_model=RouteRisk)
def get_route_risk(origin: str, dest: str):
    """Route risk analysis: origin → waypoints → destination."""
    origin = origin.upper()
    dest   = dest.upper()

    o_port = _port_row(origin)
    d_port = _port_row(dest)

    waypoints   = _route_waypoints(origin, dest)
    all_ports   = [origin] + waypoints + [dest]
    # deduplicate while preserving order
    seen = set()
    all_ports = [p for p in all_ports if not (p in seen or seen.add(p))]

    pm = _data["port_master"].set_index("locode")

    def port_name(lc):
        try: return pm.loc[lc, "port_name"]
        except: return lc

    segments = []
    cumulative_delay_prob   = 0.0
    expected_total_delay    = 0.0
    max_risk_score          = 0.0

    for i in range(len(all_ports) - 1):
        frm = all_ports[i]
        to  = all_ports[i + 1]
        frm_risk = _risk_row(frm)

        # Segment risk = risk of the "from" port (delay happens at port, not en-route)
        seg_risk  = frm_risk["risk_score"]
        seg_prob  = frm_risk["delay_prob"]
        seg_delay = frm_risk["delay_days_pred"]

        cumulative_delay_prob = 1 - (1 - cumulative_delay_prob) * (1 - seg_prob)
        expected_total_delay += seg_delay * seg_prob
        max_risk_score = max(max_risk_score, seg_risk)

        label = frm_risk["risk_label"]
        segments.append(RouteSegment(
            from_port  = frm,
            from_name  = str(port_name(frm)),
            to_port    = to,
            to_name    = str(port_name(to)),
            risk_score = round(seg_risk, 1),
            risk_label = str(label),
            delay_prob = round(seg_prob, 4),
        ))

    # Also include destination port's risk in totals
    dest_risk = _risk_row(dest)
    cumulative_delay_prob = 1 - (1 - cumulative_delay_prob) * (1 - dest_risk["delay_prob"])
    expected_total_delay += dest_risk["delay_days_pred"] * dest_risk["delay_prob"]
    max_risk_score = max(max_risk_score, dest_risk["risk_score"])

    route_label = "green" if max_risk_score < 34 else ("amber" if max_risk_score < 67 else "red")

    return RouteRisk(
        origin             = origin,
        origin_name        = str(o_port.port_name),
        destination        = dest,
        destination_name   = str(d_port.port_name),
        waypoints          = waypoints,
        waypoint_names     = [str(port_name(w)) for w in waypoints],
        all_ports          = all_ports,
        segments           = segments,
        route_risk_score   = round(float(max_risk_score), 1),
        route_risk_label   = route_label,
        cumulative_delay_prob    = round(float(cumulative_delay_prob), 4),
        expected_total_delay_days = round(float(expected_total_delay), 2),
    )
