"""Operational dashboard: run history, data quality and de-identified cohort aggregates only. No patient rows."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # streamlit runs this file as a script
from config.settings import DATA_DIR, QUALITY_THRESHOLD  # noqa: E402

st.set_page_config(page_title="Healthcare Data Platform", layout="wide")
st.title("Healthcare Data Platform: pipeline monitor")
st.caption("Synthetic data only. This view shows aggregates and never displays patient-level records.")

runs = [json.loads(p.read_text()) for p in sorted((DATA_DIR / "runs").glob("*.json"))]
if not runs:
    st.info("No pipeline runs yet. Run: python -m orchestration.pipeline --generate 1000")
    st.stop()

latest = runs[-1]
steps = {s["step"]: s for s in latest["steps"]}
quality = steps.get("silver", {}).get("result", {})
last_ok = next((r for r in reversed(runs) if r["status"].startswith("succeeded")), None)

c = st.columns(5)
c[0].metric("Latest run", latest["status"])
c[1].metric("Records in", f"{sum(q['rows_in'] for q in quality.values()):,}")
c[2].metric("Valid", f"{sum(q['rows_valid'] for q in quality.values()):,}")
c[3].metric("Rejected", f"{sum(q['rows_rejected'] for q in quality.values()):,}")
if last_ok:
    age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(last_ok["finished_at"])
    c[4].metric("Data freshness", f"{age.total_seconds() / 3600:.1f} h ago")
else:
    c[4].metric("Data freshness", "never succeeded")

if latest["status"] == "failed":
    st.error(f"Latest run failed: {latest.get('error')}")

if quality:
    st.subheader("Data quality by table")
    q = pd.DataFrame(quality.values()).set_index("table")
    st.dataframe(q[["rows_in", "rows_valid", "rows_rejected", "duplicates_removed", "quality_score"]], width="stretch")
    st.caption(f"Alert threshold: quality score below {QUALITY_THRESHOLD}")

    left, right = st.columns(2)
    reasons = pd.DataFrame([{"table": t, "reason": r, "rows": n} for t, v in quality.items() for r, n in v["reject_reasons"].items()])
    left.markdown("**Rejection reasons (quarantined rows)**")
    if not reasons.empty:
        left.bar_chart(reasons.pivot_table(index="reason", columns="table", values="rows", aggfunc="sum").fillna(0))
    missing = pd.DataFrame([{"field": f"{t}.{col}", "missing %": pct} for t, v in quality.items() for col, pct in v["missing_pct"].items()])
    right.markdown("**Missing required fields (% of source rows)**")
    right.dataframe(missing[missing["missing %"] > 0], hide_index=True, width="stretch")

st.subheader("Step duration and throughput (latest run)")
rows_by_step = {"silver": sum(q["rows_in"] for q in quality.values())}
st.dataframe(pd.DataFrame([{
    "step": s["step"], "status": s["status"], "seconds": s["seconds"],
    "rows/sec": round(rows_by_step[s["step"]] / s["seconds"]) if s["step"] in rows_by_step and s["seconds"] else None,
} for s in latest["steps"]]), hide_index=True, width="stretch")

cohort_path = DATA_DIR / "gold" / "cohort_summary.parquet"
if cohort_path.exists():
    st.subheader("Cohort summary (Gold, de-identified)")
    st.dataframe(pd.read_parquet(cohort_path), hide_index=True, width="stretch")
    st.caption("Cells with fewer than 5 patients or cases are suppressed (blank).")

st.subheader("Run history")
st.dataframe(pd.DataFrame([{"run_id": r["run_id"], "status": r["status"], "seconds": r.get("duration_seconds"),
                            "started_at": r["started_at"]} for r in reversed(runs)]), hide_index=True, width="stretch")

alerts_path = DATA_DIR / "alerts.jsonl"
if alerts_path.exists():
    st.subheader("Recent alerts")
    alerts = [json.loads(line) for line in alerts_path.read_text().splitlines()[-10:]]
    st.dataframe(pd.DataFrame(alerts[::-1]), hide_index=True, width="stretch")
