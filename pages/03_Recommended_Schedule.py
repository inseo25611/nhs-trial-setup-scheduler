import importlib

import pandas as pd
import plotly.express as px
import streamlit as st

import nhs_core as _core
import nhs_solver as _nhs_solver
import ui_components as ui

# Reload local scheduling modules so Streamlit cannot mix old cached logic with new page code.
core = importlib.reload(_core)
nhs_solver = importlib.reload(_nhs_solver)
core.initialise_state()


def _series(df, column, default=None):
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _safe_int(value, default=0):
    n = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(n) else int(round(float(n)))


def _uk_date_strings(df, columns):
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(core.format_date_for_display)
    return out


st.title("Recommended Schedule")
st.caption(
    "Generate the real-date Pharmacy recommendation, review the decision summary first, then open detailed workstream dates only when needed."
)

if st.session_state.trial_table is None:
    st.warning("No trial data has been loaded. Go to **Trials** first.")
    core.render_page_navigation(
        previous_page="pages/02_Trial_Prioritisation.py",
        next_page="pages/04_Saved_Work.py",
        previous_label="Prioritise",
        next_label="Review",
    )
    st.stop()

operational = core.build_operational_view(st.session_state.trial_table, st.session_state.assumptions)
ready_mask = operational["model_ready"].fillna(False).astype(bool) if len(operational) else pd.Series(dtype=bool)
ready_count = int(ready_mask.sum()) if len(operational) else 0
completed_mask = operational["effective_trial_status"].eq(core.STATUS_COMPLETED) if len(operational) else pd.Series(dtype=bool)
completed_count = int(completed_mask.sum()) if len(operational) else 0
excluded_active_count = int(((~ready_mask) & (~completed_mask)).sum()) if len(operational) else 0
existing_count = int((ready_mask & operational["effective_trial_status"].eq(core.STATUS_IN_PROGRESS)).sum()) if len(operational) else 0
new_count = max(0, ready_count - existing_count)

ui.mini_stats([
    ("Loaded", len(operational)),
    ("Eligible", ready_count),
    ("Existing / in progress", existing_count),
    ("New / not started", new_count),
    ("Completed", completed_count),
    ("Excluded active", excluded_active_count),
])

control_left, control_right = st.columns([3, 1])
with control_left:
    if st.session_state.get("schedule_dirty") and st.session_state.get("schedule_result") is not None:
        st.warning("Inputs changed after the previous calculation. Recalculate before using the recommendation.")
    elif st.session_state.get("schedule_result") is None:
        st.info(f"{ready_count} trial(s) are currently eligible for scheduling.")
    else:
        st.success("The current schedule matches the latest saved inputs.")
with control_right:
    recalc = st.button(
        "Generate / recalculate",
        type="primary",
        use_container_width=True,
        disabled=ready_count == 0,
    )

if recalc:
    try:
        with st.spinner("Optimising Pharmacy schedule…"):
            result = nhs_solver.solve_nhs_schedule(st.session_state.trial_table, st.session_state.assumptions)
        st.session_state.schedule_result = result["schedule"]
        st.session_state.schedule_info = result.get("technical_info", {})
        core.mark_schedule_clean(auto_save=True)
        st.rerun()
    except Exception as exc:
        st.error(f"Could not generate the schedule: {exc}")

schedule = st.session_state.get("schedule_result")
if schedule is None or len(schedule) == 0:
    with st.expander(f"Why {len(operational.loc[~ready_mask]) if len(operational) else 0} trial(s) are not currently scheduled", expanded=False):
        excluded = operational.loc[~ready_mask].copy() if len(operational) else pd.DataFrame()
        if excluded.empty:
            st.caption("No excluded trials.")
        else:
            ex_view = pd.DataFrame({
                "Trial": excluded["trial_id"].astype(str),
                "Status": excluded["effective_trial_status"].map(ui.status_label),
                "Why": excluded.get("scheduling_block_reason", ""),
            })
            st.dataframe(ui.dataframe_badge_style(ex_view, status_columns=["Status"]), use_container_width=True, hide_index=True)
    core.render_page_navigation(
        previous_page="pages/02_Trial_Prioritisation.py",
        next_page="pages/04_Saved_Work.py",
        previous_label="Prioritise",
        next_label="Review",
    )
    st.stop()

schedule = core.sync_schedule_metadata(schedule, st.session_state.trial_table)

# Invalidate schedules produced under the retired CT-progress rule.
stale_ct_schedule = False
if "ct_progress_status" in schedule.columns:
    stale_ct_schedule = schedule["ct_progress_status"].astype(str).eq("Own work complete (estimated)").any()
if stale_ct_schedule:
    st.session_state.schedule_result = None
    st.session_state.schedule_info = None
    st.session_state.schedule_dirty = True
    st.warning("This schedule was calculated with an older CT-progress rule and has been cleared. Recalculate to use the current conservative CT rule.")
    st.stop()

st.session_state.schedule_result = schedule.copy()
for col in [
    "clock_start", "pharmacy_notified_date", "due_date_rec", "CT_start_rec", "CT_end_rec", "CT_capacity_end_rec",
    "Aseptic_start_rec", "Aseptic_end_rec", "ePMA_start_rec", "ePMA_end_rec", "completion_rec",
]:
    if col in schedule.columns:
        schedule[col] = pd.to_datetime(schedule[col], errors="coerce")

margin = pd.to_numeric(_series(schedule, "margin_days"), errors="coerce")
planning_date = pd.Timestamp(st.session_state.assumptions["planning_date"])
ct_capacity_mode = str(st.session_state.assumptions.get("ct_capacity_mode", "continuous"))

n_on_time = int((margin >= 0).sum())
n_late = int((margin < 0).sum())
n_inherited = int(pd.to_numeric(_series(schedule, "inherited_overdue_days", 0), errors="coerce").fillna(0).gt(0).sum())
avg_margin = margin.mean() if margin.notna().any() else float("nan")
avg_margin_text = "N/A" if pd.isna(avg_margin) else f"{avg_margin:+.1f} days"

m1, m2, m3, m4 = st.columns(4)
ui.metric_card(m1, "Scheduled", len(schedule), tone="primary")
ui.metric_card(m2, "Predicted on time", n_on_time, tone="success")
ui.metric_card(m3, "Predicted late", n_late, tone="danger" if n_late else "success")
ui.metric_card(m4, "Average margin", avg_margin_text, tone="success" if pd.notna(avg_margin) and avg_margin >= 0 else "danger")
ui.mini_stats([("Already overdue at snapshot", n_inherited), ("CT capacity rule", "Continuous oversight" if ct_capacity_mode == "continuous" else "Active work only")])

info = st.session_state.get("schedule_info") or {}
with st.expander("Solution quality & technical status", expanded=False):
    c1, c2, c3 = st.columns(3)
    c1.write(f"Step 1: **{info.get('status_step1', 'Unknown')}**")
    c2.write(f"Step 2: **{info.get('status_step2', 'Unknown')}**")
    gap = info.get("step2_gap_pct")
    c3.write(f"Step-2 gap: **{gap:.2f}%**" if isinstance(gap, (int, float)) else "Step-2 gap: **N/A**")
    if info.get("reproducible_mode"):
        st.caption("Reproducible mode is active: fixed seed, deterministic search configuration and canonicalisation of the Step-2 incumbent.")

summary_tab, detail_tab, timeline_tab, export_tab = st.tabs([
    "Summary", "Detailed schedule", "Gantt", "Export"
])

with summary_tab:
    st.markdown("#### Decision summary")
    st.caption("This is the default operational view: rank, due date, expected completion, margin and decision.")
    summary = pd.DataFrame({
        "Rank": pd.to_numeric(schedule["final_rank"], errors="coerce").astype("Int64"),
        "Trial": schedule["trial_id"].astype(str),
        "Status": _series(schedule, "effective_trial_status", "").map(ui.status_label),
        "55-day due": _series(schedule, "due_date_rec").map(core.format_date_for_display),
        "Expected completion": _series(schedule, "completion_rec").map(core.format_date_for_display),
        "Margin": _series(schedule, "margin_days").map(ui.margin_label),
        "Decision": _series(schedule, "final_decision", "").fillna("").replace("", "—"),
    }).sort_values("Rank")
    st.dataframe(
        ui.dataframe_badge_style(summary, status_columns=["Status"], margin_columns=["Margin"]),
        use_container_width=True,
        hide_index=True,
    )

    late = schedule.loc[margin < 0].copy()
    if len(late):
        st.markdown("#### Predicted-late trials")
        late_view = pd.DataFrame({
            "Trial": late["trial_id"].astype(str),
            "Due": late["due_date_rec"].map(core.format_date_for_display),
            "Expected completion": late["completion_rec"].map(core.format_date_for_display),
            "Margin": late["margin_days"].map(ui.margin_label),
            "Priority": pd.to_numeric(_series(late, "effective_priority_score"), errors="coerce"),
        }).sort_values("Margin")
        st.dataframe(ui.dataframe_badge_style(late_view, margin_columns=["Margin"]), use_container_width=True, hide_index=True)

with detail_tab:
    st.markdown("#### Detailed workstream schedule")
    st.caption(
        "Use this view for audit/detail rather than first-line decision making. Aseptic and ePMA can start after the configured CT handoff and may run in parallel with ongoing CT work."
    )
    detailed = pd.DataFrame({
        "Rank": pd.to_numeric(schedule["final_rank"], errors="coerce").astype("Int64"),
        "Trial": schedule["trial_id"].astype(str),
        "Status": _series(schedule, "effective_trial_status", "").map(ui.status_label),
        "Queue type": _series(schedule, "queue_type", ""),
        "CT progress": _series(schedule, "ct_progress_status", "").map(ui.status_label),
        "Aseptic progress": _series(schedule, "aseptic_progress_status", "").map(ui.status_label),
        "ePMA progress": _series(schedule, "epma_progress_status", "").map(ui.status_label),
        "CT start": _series(schedule, "CT_start_rec").map(core.format_date_for_display),
        "CT active-work end": _series(schedule, "CT_end_rec").map(core.format_date_for_display),
        "CT capacity held until": _series(schedule, "CT_capacity_end_rec").map(core.format_date_for_display),
        "Aseptic start": _series(schedule, "Aseptic_start_rec").map(core.format_date_for_display),
        "Aseptic end": _series(schedule, "Aseptic_end_rec").map(core.format_date_for_display),
        "ePMA start": _series(schedule, "ePMA_start_rec").map(core.format_date_for_display),
        "ePMA end": _series(schedule, "ePMA_end_rec").map(core.format_date_for_display),
        "Expected completion": _series(schedule, "completion_rec").map(core.format_date_for_display),
        "Margin": _series(schedule, "margin_days").map(ui.margin_label),
    }).sort_values("Rank")
    st.dataframe(
        ui.dataframe_badge_style(
            detailed,
            status_columns=["Status", "CT progress", "Aseptic progress", "ePMA progress"],
            margin_columns=["Margin"],
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Inspect one trial")
    trial_options = schedule.sort_values("final_rank")["trial_id"].astype(str).tolist()
    selected = st.selectbox("Trial", trial_options, key="schedule_detail_trial")
    r = schedule.loc[schedule["trial_id"].astype(str).eq(selected)].iloc[0]
    ui.trial_summary_card(
        trial=selected,
        status=r.get("effective_trial_status", ""),
        due=r.get("due_date_rec"),
        completion=r.get("completion_rec"),
        margin=r.get("margin_days"),
        priority=r.get("effective_priority_score"),
        queue_type=r.get("queue_type", ""),
    )
    workstream_rows = []
    for label, sc, ec, rem in [
        ("CT", "CT_start_rec", "CT_end_rec", "ct_remaining_bdays"),
        ("Aseptic", "Aseptic_start_rec", "Aseptic_end_rec", "aseptic_remaining_bdays"),
        ("ePMA", "ePMA_start_rec", "ePMA_end_rec", "epma_remaining_bdays"),
    ]:
        remaining = _safe_int(r.get(rem), 0)
        if remaining <= 0:
            state = "Completed / N/A"
        else:
            state = "Scheduled"
        workstream_rows.append({
            "Workstream": label,
            "State": ui.status_label(state),
            "Start": core.format_date_for_display(r.get(sc)),
            "End": core.format_date_for_display(r.get(ec)),
            "Remaining working days": remaining,
        })
    ws_df = pd.DataFrame(workstream_rows)
    st.dataframe(ui.dataframe_badge_style(ws_df, status_columns=["State"]), use_container_width=True, hide_index=True)

    with st.expander("Complexity & duration inputs used", expanded=False):
        due_for_audit = pd.to_datetime(_series(schedule, "due_date_rec"), errors="coerce")
        audit = pd.DataFrame({
            "Trial": schedule["trial_id"].astype(str),
            "CT Complexity": _series(schedule, "ct_complexity", "Unknown"),
            "CT full days": pd.to_numeric(_series(schedule, "ct_duration_bdays"), errors="coerce"),
            "CT planning allowance": pd.to_numeric(_series(schedule, "ct_remaining_bdays", 0), errors="coerce"),
            "Aseptic full days": pd.to_numeric(_series(schedule, "aseptic_duration_bdays"), errors="coerce"),
            "Aseptic remaining": pd.to_numeric(_series(schedule, "aseptic_remaining_bdays", 0), errors="coerce"),
            "ePMA Complexity": _series(schedule, "epma_complexity", "N/A"),
            "ePMA full days": pd.to_numeric(_series(schedule, "epma_duration_bdays"), errors="coerce"),
            "ePMA remaining": pd.to_numeric(_series(schedule, "epma_remaining_bdays", 0), errors="coerce"),
            "55-day due": due_for_audit.map(core.format_date_for_display),
            "Calendar days left": (due_for_audit - planning_date).dt.days,
        })
        st.dataframe(audit, use_container_width=True, hide_index=True)

with timeline_tab:
    st.markdown("#### Gantt view")
    st.caption(
        "Green = observed tracker progress; blue = recommended future work. Switch the grouping depending on whether you are reviewing a trial journey or resource workload."
    )
    control1, control2 = st.columns([1, 3])
    with control1:
        view_mode = st.radio("Group Gantt", ["By trial", "By resource"], horizontal=False, key="gantt_group_mode")
    with control2:
        ordered_ids = schedule.sort_values("final_rank")["trial_id"].astype(str).tolist()
        selected_trials = st.multiselect(
            "Trials shown",
            ordered_ids,
            default=ordered_ids,
            help="Reduce the selection when the portfolio is large to make the timeline easier to read.",
            key="gantt_trials_shown",
        )

    rows = []
    workstream_order = {"CT": 0, "Aseptic": 1, "ePMA": 2}
    for _, r in schedule.loc[schedule["trial_id"].astype(str).isin(selected_trials)].iterrows():
        trial = str(r["trial_id"])
        rank = _safe_int(r.get("final_rank"), 0)
        observed_specs = [
            ("CT", "observed_pharmacy_setup_start", None),
            ("Aseptic", "observed_aseptic_notify", "observed_aseptic_bmr_authorised"),
            ("ePMA", "observed_iqemo_setup", "observed_iqemo_authorised"),
        ]
        for workstream, start_col, end_col in observed_specs:
            start = pd.to_datetime(r.get(start_col), errors="coerce")
            if pd.isna(start):
                continue
            end = planning_date if end_col is None else pd.to_datetime(r.get(end_col), errors="coerce")
            if pd.isna(end):
                end = planning_date
            end = min(pd.Timestamp(end), planning_date)
            if end < start:
                continue
            lane = f"{rank}. {trial} · {workstream}" if view_mode == "By trial" else f"{workstream} · {rank}. {trial}"
            rows.append({
                "Lane": lane,
                "Trial": trial,
                "Rank": rank,
                "Workstream": workstream,
                "Workstream order": workstream_order[workstream],
                "Segment type": "Observed progress",
                "Start": start,
                "End": end,
                "Detail": "Recorded tracker milestone(s) up to the planning date",
            })

        future_specs = [
            ("CT", "CT_start_rec", "CT_end_rec", "ct_remaining_bdays"),
            ("Aseptic", "Aseptic_start_rec", "Aseptic_end_rec", "aseptic_remaining_bdays"),
            ("ePMA", "ePMA_start_rec", "ePMA_end_rec", "epma_remaining_bdays"),
        ]
        for workstream, sc, ec, remaining_col in future_specs:
            remaining = pd.to_numeric(r.get(remaining_col), errors="coerce")
            if pd.isna(remaining) or float(remaining) <= 0:
                continue
            start = pd.to_datetime(r.get(sc), errors="coerce")
            end = pd.to_datetime(r.get(ec), errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue
            lane = f"{rank}. {trial} · {workstream}" if view_mode == "By trial" else f"{workstream} · {rank}. {trial}"
            rows.append({
                "Lane": lane,
                "Trial": trial,
                "Rank": rank,
                "Workstream": workstream,
                "Workstream order": workstream_order[workstream],
                "Segment type": "Recommended remaining work",
                "Start": start,
                "End": end,
                "Detail": f"{int(remaining)} remaining working day(s)",
            })

    if rows:
        timeline = pd.DataFrame(rows)
        if view_mode == "By trial":
            timeline = timeline.sort_values(["Rank", "Workstream order", "Start"])
        else:
            timeline = timeline.sort_values(["Workstream order", "Rank", "Start"])
        lane_order = timeline["Lane"].drop_duplicates().tolist()
        fig = px.timeline(
            timeline,
            x_start="Start",
            x_end="End",
            y="Lane",
            color="Segment type",
            text="Workstream",
            hover_data=["Trial", "Workstream", "Detail"],
            category_orders={"Lane": lane_order},
            color_discrete_map={
                "Observed progress": ui.GREEN_SOFT,
                "Recommended remaining work": ui.PRIMARY_SOFT,
            },
        )
        fig.update_traces(textposition="inside", textfont_color=ui.INK)
        fig.update_yaxes(autorange="reversed", title=None)
        fig.add_vline(x=planning_date, line_width=1.5, line_dash="dash", line_color=ui.GREY)
        fig.update_layout(
            height=max(520, 24 * timeline["Lane"].nunique() + 170),
            legend_title_text="",
            bargap=0.14,
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Planning-date divider: {planning_date.strftime('%d/%m/%Y')}. Default CT → specialist handoff is {int(st.session_state.assumptions.get('specialist_handoff_bdays', 2))} working days."
        )
    else:
        st.caption("No observed or recommended workstream dates are available for the selected trials.")

    with st.expander("Temporary capacity reductions applied", expanded=False):
        exceptions = st.session_state.assumptions.get("capacity_exceptions", [])
        if exceptions:
            ex_df = pd.DataFrame(exceptions).rename(columns={
                "workstream": "Workstream", "start_date": "From", "end_date": "To",
                "available_capacity": "Available capacity", "note": "Reason",
            })
            for col in ["From", "To"]:
                if col in ex_df.columns:
                    ex_df[col] = ex_df[col].map(core.format_date_for_display)
            st.dataframe(ex_df, use_container_width=True, hide_index=True)
        else:
            st.caption("None")

with export_tab:
    st.markdown("#### Export the current recommendation")
    export_schedule = core.sync_schedule_metadata(schedule, st.session_state.trial_table)
    export_cols = [
        "final_rank", "trial_id", "effective_trial_status", "clock_start", "pharmacy_notified_date",
        "due_date_rec", "manual_rank", "final_decision", "ct_complexity", "ct_duration_bdays",
        "CT_start_rec", "CT_end_rec", "CT_capacity_end_rec", "aseptic_duration_bdays", "Aseptic_start_rec", "Aseptic_end_rec",
        "epma_complexity", "epma_duration_bdays", "ePMA_start_rec", "ePMA_end_rec",
        "completion_rec", "margin_days", "schedule_status", "pharmacy_note",
    ]
    export_df = export_schedule[[c for c in export_cols if c in export_schedule.columns]].copy()
    export_df = export_df.rename(columns={
        "final_rank": "Rank", "trial_id": "Trial", "effective_trial_status": "Status",
        "clock_start": "55-day clock start", "pharmacy_notified_date": "Pharmacy notified",
        "due_date_rec": "55-day due", "manual_rank": "Manual Rank", "final_decision": "Final decision",
        "ct_complexity": "CT Complexity", "ct_duration_bdays": "CT days",
        "CT_start_rec": "CT start", "CT_end_rec": "CT active-work end", "CT_capacity_end_rec": "CT capacity held until",
        "aseptic_duration_bdays": "Aseptic days", "Aseptic_start_rec": "Aseptic start", "Aseptic_end_rec": "Aseptic end",
        "epma_complexity": "ePMA Complexity", "epma_duration_bdays": "ePMA days",
        "ePMA_start_rec": "ePMA start", "ePMA_end_rec": "ePMA end",
        "completion_rec": "Expected completion", "margin_days": "Margin days",
        "schedule_status": "Schedule status", "pharmacy_note": "Pharmacy Note",
    })
    export_date_cols = [
        "55-day clock start", "Pharmacy notified", "55-day due", "CT start", "CT active-work end", "CT capacity held until",
        "Aseptic start", "Aseptic end", "ePMA start", "ePMA end", "Expected completion",
    ]
    csv_df = _uk_date_strings(export_df, export_date_cols)
    st.download_button(
        "Download schedule CSV",
        csv_df.to_csv(index=False).encode("utf-8-sig"),
        "pharmacy_schedule.csv",
        "text/csv",
        use_container_width=True,
    )
    excel_bytes = core.dataframe_to_excel_bytes(
        export_df,
        sheet_name="Recommended Schedule",
        date_columns=export_date_cols,
        preferred_widths={"Trial": 28, "Final decision": 26, "Pharmacy Note": 55},
    )
    st.download_button(
        "Download schedule Excel",
        excel_bytes,
        "pharmacy_schedule.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

core.render_page_navigation(
    previous_page="pages/02_Trial_Prioritisation.py",
    next_page="pages/04_Saved_Work.py",
    previous_label="Prioritise",
    next_label="Review",
)
