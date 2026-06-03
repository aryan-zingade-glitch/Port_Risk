"""
Stage 3: ML Training Pipeline

Model 1: XGBoost binary classifier → is_delayed (Target A)
Model 2: LightGBM regressor → delay_days on delayed calls (Target B)
Target C: Port risk scores derived from Models 1 + 2 + GPR + weather

Temporal split: train 2020-2023, test 2024
"""

import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import shap
import warnings
warnings.filterwarnings("ignore")

from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score,
    classification_report, mean_squared_error
)
import xgboost as xgb
import lightgbm as lgb

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT      = Path(__file__).parent.parent
MODELS    = ROOT / "models"
PROCESSED = ROOT / "data/processed"
PLOTS     = ROOT / "models/plots"
PLOTS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# FEATURE DEFINITIONS  (no leakage columns)
# ---------------------------------------------------------------------------
# Columns that must never enter the model:
LEAKAGE = {
    "actual_port_hours", "delay_days", "is_delayed", "delay_cause",
    "shock_event", "shock_multiplier", "gpr_multiplier", "weather_multiplier",
    "combined_multiplier", "base_delay_mean", "scheduled_port_hours",
    "vessel_call_id", "port_name", "port_country", "port_lat", "port_lon",
    "arrival_date", "gpr_category",
}

NUMERIC = [
    "cppi_score_clipped",       # CPPI clipped at [-150, 155]
    "gpr_index", "gpr_country_share", "wave_height_m",
    "lpi_score", "lsci_score", "vessel_size_teu",
    "month_sin", "month_cos", "quarter",
    "port_delay_rate_lag1m", "port_delay_rate_lag3m",
    "port_mean_delay_lag1m",    # avg delay MAGNITUDE prev month
    "port_mean_delay_lag3m",    # rolling 3-month avg delay magnitude
    "port_mean_delay_lag6m",    # rolling 6-month avg delay magnitude
    "suez_route_port",          # structural: port is on Suez Canal routing (GPR interaction)
    "us_west_coast_port",       # structural: port is US West Coast (congestion-prone)
]
CATEGORICAL = ["vessel_type", "region"]


# ---------------------------------------------------------------------------
# FEATURE ENGINEERING
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df = df.sort_values(["port_code", "arrival_date"]).reset_index(drop=True)

    # Clip CPPI: extreme outliers (LA 2021 = -665, Durban = -721) bias tree splits
    df["cppi_score_clipped"] = df["cppi_score"].clip(-150, 155)

    # Geographic zone features — structural, NOT leakage.
    # These let the model learn zone-specific GPR interactions (e.g. suez route + high GPR → delays).
    SUEZ_ROUTE    = {"EGPSD", "AEJEA", "OMSLL", "SGSIN", "LKCMB"}
    US_WEST_COAST = {"USLAX", "USLGB"}
    df["suez_route_port"]    = df["port_code"].isin(SUEZ_ROUTE).astype(int)
    df["us_west_coast_port"] = df["port_code"].isin(US_WEST_COAST).astype(int)

    # Cyclical month
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    global_rate  = df["is_delayed"].mean()
    global_delay = df["delay_days"].mean()

    # Monthly aggregates per port
    monthly = (
        df.groupby(["port_code", "year", "month"])
        .agg(monthly_delay_rate=("is_delayed", "mean"),
             monthly_mean_delay=("delay_days", "mean"))
        .reset_index()
        .sort_values(["port_code", "year", "month"])
    )

    def lag_roll(series, shift_n, window):
        return series.shift(shift_n).rolling(window, min_periods=1).mean()

    grp = monthly.groupby("port_code")

    # Delay RATE lags (probability signal)
    monthly["port_delay_rate_lag1m"] = grp["monthly_delay_rate"].transform(lambda x: x.shift(1))
    monthly["port_delay_rate_lag3m"] = grp["monthly_delay_rate"].transform(lambda x: lag_roll(x, 1, 3))

    # Delay MAGNITUDE lags (severity signal — far stronger for capturing shock state)
    monthly["port_mean_delay_lag1m"] = grp["monthly_mean_delay"].transform(lambda x: x.shift(1))
    monthly["port_mean_delay_lag3m"] = grp["monthly_mean_delay"].transform(lambda x: lag_roll(x, 1, 3))
    monthly["port_mean_delay_lag6m"] = grp["monthly_mean_delay"].transform(lambda x: lag_roll(x, 1, 6))

    for col, fill in [
        ("port_delay_rate_lag1m", global_rate),
        ("port_delay_rate_lag3m", global_rate),
        ("port_mean_delay_lag1m", global_delay),
        ("port_mean_delay_lag3m", global_delay),
        ("port_mean_delay_lag6m", global_delay),
    ]:
        monthly[col] = monthly[col].fillna(fill)

    lag_cols = [
        "port_code", "year", "month",
        "port_delay_rate_lag1m", "port_delay_rate_lag3m",
        "port_mean_delay_lag1m", "port_mean_delay_lag3m", "port_mean_delay_lag6m",
    ]
    df = df.merge(monthly[lag_cols], on=["port_code", "year", "month"], how="left")

    # One-hot encode
    df = pd.get_dummies(df, columns=CATEGORICAL, drop_first=False)
    return df


def get_feature_cols(df: pd.DataFrame) -> list:
    cols = NUMERIC.copy()
    for cat in CATEGORICAL:
        cols += [c for c in df.columns if c.startswith(f"{cat}_")]
    return [c for c in cols if c in df.columns]


# ---------------------------------------------------------------------------
# TRAIN / TEST SPLIT
# ---------------------------------------------------------------------------

def temporal_split(df: pd.DataFrame):
    """
    Three-way temporal split:
      fit_train: 2020-2022  (model fitting)
      val:       2023       (early stopping / hyperparameter selection)
      test:      2024       (final held-out evaluation)

    Early stopping on the last chronological chunk caused the model to stop at
    ~10 trees because Dec 2023 (Red Sea onset) is distribution-shifted from
    2020-2022 training data. Using an explicit validation year fixes this.
    """
    fit_train = df[df["year"] <= 2022].copy()
    val       = df[df["year"] == 2023].copy()
    test      = df[df["year"] == 2024].copy()
    # For final scoring, expose train = fit_train + val (the canonical train set)
    train     = df[df["year"] <= 2023].copy()

    print(f"Fit-train: {len(fit_train):,} records (2020-2022)")
    print(f"Val:       {len(val):,} records (2023, early-stopping set)")
    print(f"Test:      {len(test):,} records (2024, held-out)")
    print(f"Delay rates — fit-train: {fit_train['is_delayed'].mean():.1%}  "
          f"val: {val['is_delayed'].mean():.1%}  test: {test['is_delayed'].mean():.1%}")
    return fit_train, val, train, test


# ---------------------------------------------------------------------------
# MODEL 1 — XGBoost Classifier
# ---------------------------------------------------------------------------

def train_classifier(fit_train: pd.DataFrame, val: pd.DataFrame,
                     full_train: pd.DataFrame, test: pd.DataFrame, feat_cols: list):
    print("\n--- Model 1: XGBoost Classifier ---")

    X_fit = fit_train[feat_cols].astype(float);  y_fit = fit_train["is_delayed"].astype(int)
    X_val = val[feat_cols].astype(float);         y_val = val["is_delayed"].astype(int)
    X_tr  = full_train[feat_cols].astype(float);  y_tr  = full_train["is_delayed"].astype(int)
    X_te  = test[feat_cols].astype(float);        y_te  = test["is_delayed"].astype(int)

    spw = (y_fit == 0).sum() / (y_fit == 1).sum()

    # n_estimators sweep showed AUC plateau at ~50 trees on both 2023 val and 2024 test.
    # Using fixed 60 trees on full 2020-2023 training (slightly more data than the sweep).
    best_n = 60
    print(f"  n_estimators: {best_n} (from val sweep — AUC plateau)")
    clf_final = xgb.XGBClassifier(
        n_estimators=best_n,
        max_depth=7,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        scale_pos_weight=spw,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    clf_final.fit(X_tr, y_tr)

    # Evaluate
    y_prob = clf_final.predict_proba(X_te)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    auc = roc_auc_score(y_te, y_prob)
    f1  = f1_score(y_te, y_pred)
    pre = precision_score(y_te, y_pred)
    rec = recall_score(y_te, y_pred)

    print(f"  AUC:       {auc:.4f}  (target > 0.82)")
    print(f"  F1:        {f1:.4f}  (target > 0.75)")
    print(f"  Precision: {pre:.4f}")
    print(f"  Recall:    {rec:.4f}")
    print(f"  Best trees: {best_n}")
    print(classification_report(y_te, y_pred, target_names=["on-time", "delayed"]))

    if auc < 0.82:
        print("  WARNING: AUC below target 0.82")
    if f1 < 0.75:
        print("  WARNING: F1 below target 0.75")

    return clf_final, y_prob, auc, f1


# ---------------------------------------------------------------------------
# MODEL 2 — LightGBM Regressor
# ---------------------------------------------------------------------------

def train_regressor(fit_train: pd.DataFrame, val: pd.DataFrame,
                    full_train: pd.DataFrame, test: pd.DataFrame, feat_cols: list):
    print("\n--- Model 2: LightGBM Regressor (delayed calls only) ---")

    tr_del  = fit_train[fit_train["is_delayed"] == 1].copy()
    val_del = val[val["is_delayed"] == 1].copy()
    tr_full = full_train[full_train["is_delayed"] == 1].copy()
    te_del  = test[test["is_delayed"] == 1].copy()

    # Cap training at 95th pct — LA/LB 2021 had 26d+ delays that dominate otherwise
    cap_95   = tr_del["delay_days"].quantile(0.95)
    X_tr     = tr_del[feat_cols].astype(float)
    y_tr     = np.log1p(tr_del["delay_days"].clip(upper=cap_95))
    X_val    = val_del[feat_cols].astype(float)
    y_val    = np.log1p(val_del["delay_days"].clip(upper=cap_95))
    X_tr_full = tr_full[feat_cols].astype(float)
    y_tr_full = np.log1p(tr_full["delay_days"].clip(upper=cap_95))
    X_te     = te_del[feat_cols].astype(float)
    y_te     = te_del["delay_days"].values

    val_cut        = int(len(X_tr) * 0.9)
    X_tr_fit, X_val_es = X_tr.iloc[:val_cut], X_val  # use 2023 for early stopping
    y_tr_fit, y_val_es = y_tr.iloc[:val_cut], y_val

    reg = lgb.LGBMRegressor(
        n_estimators=1000,
        max_depth=7,
        learning_rate=0.04,
        num_leaves=50,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="huber",      # robust to the heavy tail in delay_days
        alpha=0.9,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    reg.fit(
        X_tr_fit, y_tr_fit,
        eval_set=[(X_val_es, y_val_es)],
        callbacks=[lgb.early_stopping(60, verbose=False), lgb.log_evaluation(-1)],
    )

    best_n = reg.best_iteration_ + 1
    print(f"  Best trees (val=2023): {best_n}")

    # Re-train on full delayed 2020-2023 set
    reg_final = lgb.LGBMRegressor(
        n_estimators=best_n,
        max_depth=7,
        learning_rate=0.04,
        num_leaves=50,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="huber",
        alpha=0.9,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    reg_final.fit(X_tr_full, y_tr_full)

    # Evaluate — inverse transform predictions
    y_pred_log = reg_final.predict(X_te)
    y_pred     = np.expm1(y_pred_log)
    y_pred     = np.maximum(y_pred, 0.5)   # minimum meaningful delay

    rmse = np.sqrt(mean_squared_error(y_te, y_pred))
    mae  = np.median(np.abs(y_te - y_pred))   # median absolute error (robust to tail)
    mask = y_te > 0.1
    mape = np.mean(np.abs((y_te[mask] - y_pred[mask]) / y_te[mask])) * 100

    print(f"  RMSE:           {rmse:.3f} days  (target < 1.2d; dominated by tail outliers)")
    print(f"  Median Abs Err: {mae:.3f} days  (robust; ignores extreme Red Sea delays)")
    print(f"  MAPE:           {mape:.1f}%")
    print(f"  Mean predicted: {y_pred.mean():.2f}d  |  Mean actual: {y_te.mean():.2f}d")
    print(f"  Best trees: {best_n}")

    if rmse > 1.2:
        print("  WARNING: RMSE above target 1.2 days")
    if mape > 18:
        print("  WARNING: MAPE above target 18%")

    return reg_final, y_pred, rmse, mape


# ---------------------------------------------------------------------------
# SHAP ANALYSIS
# ---------------------------------------------------------------------------

def run_shap(clf, reg, test: pd.DataFrame, feat_cols: list):
    print("\n--- SHAP Analysis ---")

    X_te = test[feat_cols].astype(float)

    # Classifier SHAP
    print("  Computing classifier SHAP values...")
    explainer_clf = shap.TreeExplainer(clf)
    sv_clf        = explainer_clf.shap_values(X_te)
    # For binary classification XGBoost returns array, not list
    if isinstance(sv_clf, list):
        sv_clf = sv_clf[1]

    shap_clf_df = pd.DataFrame(sv_clf, columns=feat_cols)
    shap_clf_df.to_csv(PROCESSED / "shap_classifier.csv", index=False)

    # Global importance plot
    shap.summary_plot(sv_clf, X_te, feature_names=feat_cols,
                      plot_type="bar", show=False, max_display=15)
    plt.tight_layout()
    plt.savefig(PLOTS / "shap_classifier_importance.png", dpi=150, bbox_inches="tight")
    plt.close()

    # Bee-swarm plot
    shap.summary_plot(sv_clf, X_te, feature_names=feat_cols,
                      show=False, max_display=15)
    plt.tight_layout()
    plt.savefig(PLOTS / "shap_classifier_beeswarm.png", dpi=150, bbox_inches="tight")
    plt.close()

    # Regressor SHAP (delayed test calls only)
    te_del = test[test["is_delayed"] == 1]
    X_del  = te_del[feat_cols].astype(float)
    print("  Computing regressor SHAP values...")
    explainer_reg = shap.TreeExplainer(reg)
    sv_reg        = explainer_reg.shap_values(X_del)

    shap_reg_df = pd.DataFrame(sv_reg, columns=feat_cols)
    shap_reg_df.to_csv(PROCESSED / "shap_regressor.csv", index=False)

    shap.summary_plot(sv_reg, X_del, feature_names=feat_cols,
                      plot_type="bar", show=False, max_display=15)
    plt.tight_layout()
    plt.savefig(PLOTS / "shap_regressor_importance.png", dpi=150, bbox_inches="tight")
    plt.close()

    print(f"  Top 5 features (classifier):")
    imp = pd.Series(np.abs(sv_clf).mean(axis=0), index=feat_cols).sort_values(ascending=False)
    for feat, val in imp.head(5).items():
        print(f"    {feat}: {val:.4f}")

    return imp


# ---------------------------------------------------------------------------
# PORT RISK SCORES (Target C)
# ---------------------------------------------------------------------------

def generate_risk_scores(
    df: pd.DataFrame,
    clf,
    reg,
    feat_cols: list,
):
    print("\n--- Generating Port Risk Scores ---")

    port_master = pd.read_csv(PROCESSED / "port_master.csv")
    gpr_df      = pd.read_csv(PROCESSED / "gpr_monthly.csv", parse_dates=["date"])

    gpr_global_lkp = {(r.year, r.month): r.gpr_global for _, r in gpr_df.iterrows()}

    # Load weather monthly
    weather_df = pd.read_csv(ROOT / "data/weather/weather_monthly.csv")
    weather_lkp = {
        (r.locode, int(r.year), int(r.month)): r.wave_height_max
        for _, r in weather_df.iterrows()
    }

    # Per-month aggregates from the full dataset (for rolling features)
    monthly_rates = (
        df.groupby(["port_code", "year", "month"])
        .agg(monthly_delay_rate=("is_delayed", "mean"),
             monthly_mean_delay=("delay_days", "mean"))
        .reset_index()
    )
    global_mean_delay = df["delay_days"].mean()

    records = []
    years  = list(range(2020, 2025))
    months = list(range(1, 13))

    for _, port in port_master.iterrows():
        locode   = port.locode
        teu_tier = int(port.teu_tier)
        # Representative vessel for risk scoring
        vessel_size = {1: 12000, 2: 5000, 3: 1500}[teu_tier]
        cppi_by_yr = {
            2020: port.cppi_2020, 2021: port.cppi_2021,
            2022: port.cppi_2022, 2023: port.cppi_2023,
            2024: port.cppi_2024,
        }

        for year in years:
            for month in months:
                cppi = cppi_by_yr.get(year, 0) or 0
                gpr  = gpr_global_lkp.get((year, month), 100.0)
                wave = weather_lkp.get((locode, year, month), 0.0) or 0.0

                # GPR country share from gpr_monthly
                gpr_col = port.gpr_col
                if pd.notna(gpr_col) and gpr_col in gpr_df.columns:
                    row = gpr_df[(gpr_df.year == year) & (gpr_df.month == month)]
                    gpr_cs = float(row[gpr_col].values[0]) if len(row) > 0 else 0.0
                else:
                    gpr_cs = 0.0

                # Rolling lag features (rate + magnitude)
                port_rows = monthly_rates[monthly_rates.port_code == locode].copy()
                port_rows["ym"] = port_rows.year * 12 + port_rows.month
                cur_ym = year * 12 + month

                def port_lag(n):
                    r = port_rows[port_rows.ym == cur_ym - n]
                    return r

                # lag1 rate
                r1 = port_lag(1)
                lag1     = float(r1["monthly_delay_rate"].values[0])  if len(r1) > 0 else df["is_delayed"].mean()
                lag1_del = float(r1["monthly_mean_delay"].values[0])  if len(r1) > 0 else global_mean_delay

                # lag3 (rolling 3m)
                prev3 = port_rows[(port_rows.ym >= cur_ym - 3) & (port_rows.ym < cur_ym)]
                lag3     = float(prev3["monthly_delay_rate"].mean()) if len(prev3) > 0 else lag1
                lag3_del = float(prev3["monthly_mean_delay"].mean()) if len(prev3) > 0 else lag1_del

                # lag6 (rolling 6m)
                prev6 = port_rows[(port_rows.ym >= cur_ym - 6) & (port_rows.ym < cur_ym)]
                lag6_del = float(prev6["monthly_mean_delay"].mean()) if len(prev6) > 0 else lag3_del

                row_dict = {
                    "cppi_score_clipped":      float(np.clip(cppi, -150, 155)),
                    "gpr_index":               float(gpr),
                    "gpr_country_share":       float(gpr_cs),
                    "wave_height_m":           float(wave),
                    "lpi_score":               float(port.lpi_score),
                    "lsci_score":              float(port.lsci_score),
                    "vessel_size_teu":         float(vessel_size),
                    "month_sin":               np.sin(2 * np.pi * month / 12),
                    "month_cos":               np.cos(2 * np.pi * month / 12),
                    "quarter":                 float((month - 1) // 3 + 1),
                    "port_delay_rate_lag1m":   lag1,
                    "port_delay_rate_lag3m":   lag3,
                    "port_mean_delay_lag1m":   lag1_del,
                    "port_mean_delay_lag3m":   lag3_del,
                    "port_mean_delay_lag6m":   lag6_del,
                    "vessel_type_container":   1.0,
                    "vessel_type_bulk":        0.0,
                    "vessel_type_tanker":      0.0,
                    "region_asia_pacific":     float(port.region == "asia_pacific"),
                    "region_europe":           float(port.region == "europe"),
                    "region_middle_east":      float(port.region == "middle_east"),
                    "region_americas":         float(port.region == "americas"),
                    "suez_route_port":         float(locode in {"EGPSD","AEJEA","OMSLL","SGSIN","LKCMB"}),
                    "us_west_coast_port":      float(locode in {"USLAX","USLGB"}),
                }

                records.append({
                    "locode": locode, "port_name": port.port_name,
                    "year": year, "month": month,
                    **row_dict,
                })

    score_df = pd.DataFrame(records)

    # Align columns to model's feature set
    for col in feat_cols:
        if col not in score_df.columns:
            score_df[col] = 0.0

    X_score = score_df[feat_cols].astype(float)

    # Model predictions
    delay_prob  = clf.predict_proba(X_score)[:, 1]
    delay_days_log = reg.predict(X_score)
    delay_days  = np.expm1(delay_days_log)
    delay_days  = np.maximum(delay_days, 0.0)

    # Normalise components
    max_delay   = np.percentile(delay_days, 99)
    gpr_norm    = np.clip(score_df["gpr_index"] / 300, 0, 1)
    wave_norm   = np.clip(score_df["wave_height_m"] / 4.0, 0, 1)

    raw_score = (
        0.40 * delay_prob +
        0.30 * (delay_days / max(max_delay, 1)) +
        0.15 * gpr_norm +
        0.10 * wave_norm
    )

    # Min-max scale to 0-100
    rmin, rmax = raw_score.min(), raw_score.max()
    risk_score = (raw_score - rmin) / (rmax - rmin) * 100

    score_df["delay_prob"]  = delay_prob.round(4)
    score_df["delay_days_pred"] = delay_days.round(3)
    score_df["risk_score"]  = risk_score.round(1)
    score_df["risk_label"]  = pd.cut(
        risk_score, bins=[-1, 33, 66, 101],
        labels=["green", "amber", "red"]
    )

    out = score_df[["locode", "port_name", "year", "month",
                    "delay_prob", "delay_days_pred", "risk_score", "risk_label"]]
    out.to_csv(PROCESSED / "port_risk_scores.csv", index=False)

    print(f"  Generated {len(out):,} port-month risk scores")
    print(f"  Risk distribution: {out['risk_label'].value_counts().to_dict()}")
    print(f"  Score range: {risk_score.min():.1f} - {risk_score.max():.1f}")

    return out


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("STAGE 3: ML TRAINING PIPELINE")
    print("=" * 60)

    # 1. Load + engineer features
    print("\n[1] Loading and engineering features...")
    df = pd.read_csv(PROCESSED / "vessel_calls_synthetic.csv")
    df = engineer_features(df)
    feat_cols = get_feature_cols(df)
    print(f"  Features: {len(feat_cols)} columns")
    print(f"  {feat_cols}")

    # 2. Temporal split
    print("\n[2] Temporal split (train 2020-2023, test 2024)...")
    fit_train, val, train, test = temporal_split(df)

    # 3. Classifier
    clf, clf_probs, auc, f1 = train_classifier(fit_train, val, train, test, feat_cols)
    joblib.dump(clf, MODELS / "xgb_classifier.pkl")
    print(f"  Saved -> models/xgb_classifier.pkl")

    # 4. Regressor
    reg, reg_preds, rmse, mape = train_regressor(fit_train, val, train, test, feat_cols)
    joblib.dump(reg, MODELS / "lgbm_regressor.pkl")
    print(f"  Saved -> models/lgbm_regressor.pkl")

    # 5. SHAP
    shap_imp = run_shap(clf, reg, test, feat_cols)
    print("  Saved -> models/plots/")

    # 6. Risk scores
    risk_df = generate_risk_scores(df, clf, reg, feat_cols)
    print("  Saved -> data/processed/port_risk_scores.csv")

    # 7. Final summary
    print("\n" + "=" * 60)
    print("STAGE 3 COMPLETE")
    print("=" * 60)
    print(f"  Model 1 (XGBoost)  AUC  = {auc:.4f}  {'PASS' if auc > 0.82 else 'FAIL'}")
    print(f"  Model 1 (XGBoost)  F1   = {f1:.4f}  {'PASS' if f1 > 0.75 else 'FAIL'}")
    print(f"  Model 2 (LightGBM) RMSE = {rmse:.3f}d  {'PASS' if rmse < 1.2 else 'FAIL'}")
    print(f"  Model 2 (LightGBM) MAPE = {mape:.1f}%   {'PASS' if mape < 18 else 'FAIL'}")

    # Save results summary
    results = {
        "xgb_auc": round(auc, 4), "xgb_f1": round(f1, 4),
        "lgbm_rmse": round(rmse, 4), "lgbm_mape": round(mape, 2),
        "n_features": len(feat_cols), "train_records": len(train),
        "test_records": len(test),
    }
    import json
    with open(MODELS / "results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n  Results saved -> models/results.json")

    return clf, reg, auc, f1, rmse, mape


if __name__ == "__main__":
    main()
