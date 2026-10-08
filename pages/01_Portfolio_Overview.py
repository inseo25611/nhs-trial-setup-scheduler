import pandas as pd
import streamlit as st

import nhs_core as core
import ui_components as ui

core.initialise_state()

st.title("Pharmacy Planning Overview")
st.caption(
    "A decision-focused portfolio dashboard: what is active, what is ready to schedule, and which trials need attention first."
)

if st.session_state.trial_table is None:
    st.info("No workspace is loaded. Load the synthetic sample to explore the tool, or go to **Trials** to upload your own workbook.")
    core.render_sample_data_button(key="overview_sample")
    core.render_page_navigation(next_page="pages/06_Data_Assumptions.py", next_label="Trials")
    st.stop()

operational = core.build_operational_view(st.session_state.trial_table, st.session_state.assumptions)
if operational.empty:
    st.warning("The current workspace contains no trials.")
    core.render_page_navigation(next_page="pages/06_Data_Assumptions.py", next_label="Trials")
    st.stop()

completed = operational["effective_trial_status"].eq(core.STATUS_COMPLETED)
active = ~completed
ready = operational["model_ready"].fillna(False).astype(bool)
awaiting = operational["awaiting_pharmacy_notification"].fillna(False).astype(bool)
not_stage2 = operational["not_yet_stage2_started"].fillna(False).astype(bool)
needs_data = operational["needs_data_attention"].fillna(False).astype(bool)
escalation = operational["escalation_needed"].fillna(False).astype(bool) & active

# Only use schedule-based urgency when the recommendation still matches the current inputs.
schedule = st.session_state.get("schedule_result")
schedule_clean = schedule is not None and len(schedule) > 0 and not st.session_state.get("schedule_dirty", False)
margin_map = {}
completion_map = {}
if schedule_clean:
    live_schedule = core.sync_schedule_metadata(schedule, st.session_state.trial_table)
    if "trial_id" in live_schedule.columns:
        for _, row in live_schedule.iterrows():
            tid = str(row.get("trial_id"))
            margin_map[tid] = pd.to_numeric(row.get("margin_days"), errors="coerce")
            completion_map[tid] = pd.to_datetime(row.get("completion_rec"), errors="coerce")

predicted_late_ids = {
    tid for tid, margin in margin_map.items() if pd.notna(margin) and float(margin) < 0
}
predicted_late_count = len(predicted_late_ids) if schedule_clean else "—"

# Needs-attention KPI counts unique active trials with a genuinely actionable warning.
attention_ids = set()
for _, row in operational.loc[active].iterrows():
    tid = str(row.get("trial_id"))
    days = pd.to_numeric(row.get("days_to_55_day_due"), errors="coerce")
    if bool(row.get("needs_data_attention")) or bool(row.get("escalation_needed")) or bool(row.get("awaiting_pharmacy_notification")):
        attention_ids.add(tid)
    elif pd.notna(days) and float(days) <= 7:
        attention_ids.add(tid)
    if tid in predicted_late_ids:
        attention_ids.add(tid)

k1, k2, k3, k4 = st.columns(4)
ui.metric_card(k1, "Active portfolio", int(active.sum()), tone="primary", help_text="Excludes completed / archived trials")
ui.metric_card(k2, "Ready to schedule", int(ready.sum()), tone="primary", help_text="Eligible for the optimiser now")
ui.metric_card(k3, "Needs attention", len(attention_ids), tone="warning" if attention_ids else "success", help_text="Data, due-date or workflow follow-up")
ui.metric_card(k4, "Predicted late", predicted_late_count, tone="danger" if predicted_late_ids else ("neutral" if not schedule_clean else "success"), help_text="From the current clean schedule")

ui.mini_stats([
    ("Completed", int(completed.sum())),
    ("Awaiting Pharmacy", int(awaiting.sum())),
    ("Not yet Stage 2", int(not_stage2.sum())),
    ("Needs data", int(needs_data.sum())),
    ("Escalation", int(escalation.sum())),
])

if st.session_state.get("schedule_dirty") and schedule is not None:
    st.warning("Inputs changed after the last calculation. Schedule-based lateness is hidden until the recommendation is recalculated.")
elif schedule is None:
    st.info("No schedule has been calculated yet. Complete Trials → Capacity → Prioritise, then generate the recommendation on Schedule.")

# -----------------------------
# Urgency / action queue
# -----------------------------
st.markdown("### What needs attention now")
st.caption("Trials are ordered by operational urgency, not by the optimiser's final scheduling rank.")

urgency_rows = []
for _, row in operational.loc[active].iterrows():
    tid = str(row.get("trial_id"))
    days = pd.to_numeric(row.get("days_to_55_day_due"), errors="coerce")
    margin = margin_map.get(tid, float("nan"))
    score = 0
    reason = ""
    urgency = ""

    if bool(row.get("needs_data_attention")):
        score = 120
        reason = str(row.get("scheduling_block_reason") or "Required planning data is incomplete")
        urgency = "Needs data"
    elif pd.notna(margin) and float(margin) < 0:
        score = 110 + min(30, abs(int(float(margin))))
        reason = f"Current schedule predicts {abs(int(round(float(margin))))} day(s) late"
        urgency = "Predicted late"
    elif bool(row.get("escalation_needed")):
        score = 100
        reason = "Beyond the configured overdue escalation threshold"
        urgency = "Escalation"
    elif pd.notna(days) and float(days) < 0:
        score = 95 + min(20, abs(int(float(days))))
        reason = f"55-day due date passed {abs(int(float(days)))} day(s) ago"
        urgency = "Overdue"
    elif bool(row.get("awaiting_pharmacy_notification")):
        score = 85
        reason = "Stage 2 has started but Pharmacy notification is not yet available at this snapshot"
        urgency = "Awaiting Pharmacy"
    elif pd.notna(days) and float(days) <= 7:
        score = 75 - int(float(days))
        reason = f"55-day due date is in {int(float(days))} day(s)"
        urgency = "Due soon"
    elif pd.notna(days) and float(days) <= 14:
        score = 55 - int(float(days))
        reason = f"55-day due date is in {int(float(days))} day(s)"
        urgency = "Approaching due"

    if score > 0:
        urgency_rows.append({
            "Trial": tid,
            "Urgency": ui.status_label(urgency),
            "Reason / next action": reason,
            "Due": core.format_date_for_display(row.get("due_date")),
            "Days to due": "" if pd.isna(days) else int(float(days)),
            "Priority": pd.to_numeric(row.get("effective_priority_score"), errors="coerce"),
            "_score": score,
        })

if urgency_rows:
    urgency_df = pd.DataFrame(urgency_rows).sort_values(["_score", "Days to due"], ascending=[False, True]).drop(columns="_score")
    st.dataframe(
        ui.dataframe_badge_style(urgency_df, status_columns=["Urgency"]),
        use_container_width=True,
        hide_index=True,
        height=min(420, 38 * (len(urgency_df) + 1)),
    )
else:
    st.success("No active trial currently meets the dashboard's attention rules.")

portfolio_tab, action_tab, resource_tab = st.tabs(["Portfolio snapshot", "Eligibility & exclusions", "Resource snapshot"])

with portfolio_tab:
    st.markdown("#### Portfolio snapshot")
    st.caption("The default view keeps only decision-relevant columns. Detailed milestone editing remains on Trials.")
    view = pd.DataFrame({
        "Trial": operational["trial_id"].astype(str),
        "Status": operational["effective_trial_status"].map(ui.status_label),
        "Portfolio position": operational.get("snapshot_category", ""),
        "55-day due": operational.get("due_date", pd.Series(index=operational.index)).map(core.format_date_for_display),
        "Due status": operational.get("days_to_55_day_due", pd.Series(index=operational.index)).map(ui.due_label),
        "CT": operational.get("ct_progress_status", "").map(ui.status_label),
        "Aseptic": operational.get("aseptic_progress_status", "").map(ui.status_label),
        "ePMA": operational.get("epma_progress_status", "").map(ui.status_label),
        "Priority": pd.to_numeric(operational.get("effective_priority_score"), errors="coerce"),
        "Final decision": operational.get("final_decision", "").fillna(""),
    })
    st.dataframe(
        ui.dataframe_badge_style(view, status_columns=["Status", "Due status", "CT", "Aseptic", "ePMA"]),
        use_container_width=True,
        hide_index=True,
    )

with action_tab:
    excluded = operational.loc[~ready].copy()
    if excluded.empty:
        st.success("Every loaded trial is currently eligible for scheduling.")
    else:
        ex_view = pd.DataFrame({
            "Trial": excluded["trial_id"].astype(str),
            "Status": excluded["effective_trial_status"].map(ui.status_label),
            "Position": excluded.get("snapshot_category", ""),
            "Scheduling action": excluded.get("scheduling_action", ""),
            "Why": excluded.get("scheduling_block_reason", ""),
            "Green Light": excluded.get("observed_greenlight", pd.Series(index=excluded.index)).map(core.format_date_for_display),
        })
        st.dataframe(
            ui.dataframe_badge_style(ex_view, status_columns=["Status"]),
            use_container_width=True,
            hide_index=True,
        )

with resource_tab:
    a = st.session_state.assumptions
    c1, c2, c3, c4 = st.columns(4)
    ui.metric_card(c1, "CT capacity", int(a["cap_ct"]), tone="primary")
    ui.metric_card(c2, "Aseptic capacity", int(a["cap_aseptic"]), tone="primary")
    ui.metric_card(c3, "ePMA capacity", int(a["cap_epma"]), tone="primary")
    ui.metric_card(c4, "CT → specialist handoff", f"{int(a.get('specialist_handoff_bdays', 2))} days", tone="neutral")
    exceptions = a.get("capacity_exceptions", [])
    if exceptions:
        df = pd.DataFrame(exceptions).rename(columns={
            "workstream": "Workstream", "start_date": "From", "end_date": "To",
            "available_capacity": "Available capacity", "note": "Reason",
        })
        for col in ["From", "To"]:
            if col in df.columns:
                df[col] = df[col].map(core.format_date_for_display)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No temporary reduced-capacity periods are currently recorded.")

core.render_page_navigation(next_page="pages/06_Data_Assumptions.py", next_label="Trials")
