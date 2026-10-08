import pandas as pd
import streamlit as st

import nhs_core as core
import nhs_solver
import ui_components as ui

core.initialise_state()

st.title("Prioritise the Scheduling Queue")
st.caption(
    "See the queue order at a glance, maintain organisational priority scores, and apply a deliberate Pharmacy override when needed."
)

if st.session_state.trial_table is None:
    st.warning("No trial data has been loaded. Go to **Trials** first.")
    core.render_page_navigation(
        previous_page="pages/05_Capacity_Planning.py",
        next_page="pages/03_Recommended_Schedule.py",
        previous_label="Capacity",
        next_label="Schedule",
    )
    st.stop()

operational = core.build_operational_view(st.session_state.trial_table, st.session_state.assumptions)
completed = operational["effective_trial_status"].eq(core.STATUS_COMPLETED)
active = operational.loc[~completed].copy()
ready_mask = active["model_ready"].fillna(False).astype(bool)
queue = active.loc[ready_mask].copy()
queue_ids = queue["trial_id"].astype(str).tolist()

supplied = pd.to_numeric(active.get("priority_score"), errors="coerce").gt(0)
manual_count = pd.to_numeric(active.get("manual_rank"), errors="coerce").notna().sum()

m1, m2, m3, m4 = st.columns(4)
ui.metric_card(m1, "Active trials", len(active), tone="primary")
ui.metric_card(m2, "Scheduling queue", int(ready_mask.sum()), tone="primary")
ui.metric_card(m3, "Priority scores supplied", int(supplied.sum()), tone="success" if supplied.all() and len(active) else "warning")
ui.metric_card(m4, "Manual queue positions", int(manual_count), tone="warning" if manual_count else "neutral")


def _display_order_and_source():
    saved_manual = core.manual_queue_order(st.session_state.trial_table, st.session_state.assumptions)
    if saved_manual:
        order = [x for x in saved_manual if x in queue_ids]
        order += [x for x in queue_ids if x not in order]
        return order, "Manual Pharmacy order", saved_manual

    current_schedule = st.session_state.get("schedule_result")
    if (
        current_schedule is not None
        and len(current_schedule)
        and not st.session_state.get("schedule_dirty", False)
        and "final_rank" in current_schedule.columns
    ):
        order = (
            current_schedule.loc[current_schedule["trial_id"].astype(str).isin(queue_ids)]
            .sort_values("final_rank")["trial_id"]
            .astype(str)
            .tolist()
        )
        order += [x for x in queue_ids if x not in order]
        return order, "Current optimiser order", []

    preview = queue.copy()
    if preview.empty:
        return [], "No schedulable trials", []
    preview["_continuity"] = preview["effective_trial_status"].eq(core.STATUS_IN_PROGRESS).astype(int)
    preview["_due"] = pd.to_datetime(preview["due_date"], errors="coerce")
    preview["_priority"] = pd.to_numeric(preview["effective_priority_score"], errors="coerce").fillna(0)
    order = (
        preview.sort_values(
            ["_continuity", "_due", "_priority", "trial_id"],
            ascending=[False, True, False, True],
        )["trial_id"]
        .astype(str)
        .tolist()
    )
    return order, "Queue preview — final order is determined when the optimiser runs", []


display_order, order_source, saved_manual_order = _display_order_and_source()

st.markdown("### Recommended queue at a glance")
st.caption(order_source)
if not display_order:
    st.info("No trials are currently eligible for scheduling.")
else:
    detail = queue.copy()
    detail.index = detail["trial_id"].astype(str)
    top = display_order[:6]
    for start in range(0, len(top), 3):
        cols = st.columns(3)
        for offset, tid in enumerate(top[start:start + 3]):
            row = detail.loc[tid]
            due_days = pd.to_numeric(row.get("days_to_55_day_due"), errors="coerce")
            due_text = ui.due_label(due_days)
            priority = pd.to_numeric(row.get("effective_priority_score"), errors="coerce")
            priority_text = ui.format_priority_display(priority)
            fallback = bool(row.get("priority_is_mean_imputed"))
            ui.queue_card(
                cols[offset],
                display_order.index(tid) + 1,
                tid,
                status=row.get("effective_trial_status", ""),
                due=due_text,
                priority=priority_text,
                detail="Mean fallback used" if fallback else str(row.get("queue_type", "")),
            )
    if len(display_order) > 6:
        st.caption(f"Showing the first 6 of {len(display_order)} schedulable trials. The full order is available below.")

queue_tab, score_tab, override_tab = st.tabs(["Queue detail", "Priority scores", "Manual override"])

with queue_tab:
    if display_order:
        detail = queue.copy()
        detail.index = detail["trial_id"].astype(str)
        rows = []
        for pos, tid in enumerate(display_order, start=1):
            if tid not in detail.index:
                continue
            r = detail.loc[tid]
            rows.append({
                "Position": pos,
                "Trial": tid,
                "Status": ui.status_label(r.get("effective_trial_status", "")),
                "Due status": ui.due_label(r.get("days_to_55_day_due")),
                "Priority": (
                    pd.NA
                    if pd.isna(pd.to_numeric(r.get("effective_priority_score"), errors="coerce"))
                    else int(round(float(pd.to_numeric(r.get("effective_priority_score"), errors="coerce"))))
                ),
                "Priority source": "Mean fallback" if bool(r.get("priority_is_mean_imputed")) else "Supplied",
                "CT days": 0 if pd.isna(pd.to_numeric(r.get("ct_remaining_bdays"), errors="coerce")) else int(pd.to_numeric(r.get("ct_remaining_bdays"), errors="coerce")),
                "Aseptic days": 0 if pd.isna(pd.to_numeric(r.get("aseptic_remaining_bdays"), errors="coerce")) else int(pd.to_numeric(r.get("aseptic_remaining_bdays"), errors="coerce")),
                "ePMA days": 0 if pd.isna(pd.to_numeric(r.get("epma_remaining_bdays"), errors="coerce")) else int(pd.to_numeric(r.get("epma_remaining_bdays"), errors="coerce")),
            })
        queue_df = pd.DataFrame(rows)
        st.dataframe(
            ui.dataframe_badge_style(queue_df, status_columns=["Status", "Due status"]),
            use_container_width=True,
            hide_index=True,
        )

with score_tab:
    st.markdown("#### Maintain organisational priority")
    st.caption(
        "Blank scores use the mean of available positive scores. The fallback keeps incomplete records schedulable while remaining visibly identified as imputed."
    )
    pview = pd.DataFrame({
        "Trial": active["trial_id"].astype(str),
        "Status": active["effective_trial_status"].map(ui.status_label),
        "Due status": active["days_to_55_day_due"].map(ui.due_label),
        # Keep the stored score untouched; formatting below removes decimal places in the UI only.
        "Priority Score": pd.to_numeric(active["priority_score"], errors="coerce"),
        "Priority used": pd.to_numeric(active["effective_priority_score"], errors="coerce").round().astype("Int64"),
        "Fallback used": active["priority_is_mean_imputed"].fillna(False).astype(bool),
    })

    with st.form("priority_form"):
        pedited = st.data_editor(
            pview,
            use_container_width=True,
            hide_index=True,
            disabled=["Trial", "Status", "Due status", "Priority used", "Fallback used"],
            column_config={
                "Priority Score": st.column_config.NumberColumn(min_value=0, max_value=100, step=1, format="%d"),
                "Fallback used": st.column_config.CheckboxColumn(),
            },
        )
        save_priority = st.form_submit_button("Save priority scores", type="primary", use_container_width=True)

    if save_priority:
        table = st.session_state.trial_table.copy().reset_index(drop=True)
        changed = False
        for _, r in pedited.iterrows():
            mask = table["trial_id"].astype(str).eq(str(r["Trial"]))
            if not mask.any():
                continue
            idx = table.index[mask][0]
            new = pd.to_numeric(r["Priority Score"], errors="coerce")
            old = pd.to_numeric(table.at[idx, "priority_score"], errors="coerce")
            new_val = None if pd.isna(new) or float(new) <= 0 else float(new)
            old_val = None if pd.isna(old) or float(old) <= 0 else float(old)
            if new_val != old_val:
                table.at[idx, "priority_score"] = new_val
                changed = True
        if changed:
            st.session_state.trial_table = core.normalise_edited_trials(
                st.session_state.trial_table, table, st.session_state.assumptions
            )
            st.session_state.priority_editor_version += 1
            core.mark_schedule_dirty(auto_save=True)
            st.success("Priority scores saved. The schedule now needs recalculation.")
            st.rerun()
        else:
            st.info("No priority scores changed.")

with override_tab:
    st.markdown("#### Move one trial; let the app renumber the rest")
    st.caption(
        "A manual move changes optimiser precedence, not just the displayed row order. Capacity, release dates, workstream durations and the 2-working-day CT handoff still apply."
    )

    queue_rank_values = pd.to_numeric(queue.get("manual_rank"), errors="coerce") if len(queue) else pd.Series(dtype=float)
    any_manual_positions = bool(queue_rank_values.notna().any())

    if not display_order:
        st.info("There is nothing to override because no trials are in the scheduling queue.")
    else:
        if saved_manual_order:
            st.success("Manual queue override is active.")
        elif any_manual_positions:
            st.warning("A partial legacy manual-rank pattern was found. Applying a move will rebuild a complete 1..N order.")
        else:
            st.info("The optimiser currently controls the queue order.")

        c1, c2 = st.columns([2, 1])
        with c1:
            selected_trial = st.selectbox("Trial to move", display_order, key="priority_move_trial")
        with c2:
            current_position = display_order.index(selected_trial) + 1
            target_position = st.number_input(
                "Target position",
                min_value=1,
                max_value=len(display_order),
                value=int(current_position),
                step=1,
                key="priority_move_position",
            )

        selected_row = queue.loc[queue["trial_id"].astype(str).eq(selected_trial)].iloc[0]
        ui.trial_summary_card(
            trial=selected_trial,
            status=selected_row.get("effective_trial_status", ""),
            due=selected_row.get("due_date"),
            completion=None,
            margin=None,
            priority=pd.to_numeric(selected_row.get("effective_priority_score"), errors="coerce"),
            queue_type=selected_row.get("queue_type", ""),
        )
        st.caption(
            "Position 1 is the highest manual precedence. Multiple trials can still share a CT start date when resource capacity allows it."
        )

        apply_col, reset_col = st.columns(2)
        apply_move = apply_col.button("Apply move & recalculate", type="primary", use_container_width=True)
        reset_order = reset_col.button(
            "Return control to optimiser",
            use_container_width=True,
            disabled=not any_manual_positions,
        )

        if apply_move:
            try:
                if saved_manual_order:
                    baseline_order = saved_manual_order
                else:
                    baseline_table = core.clear_manual_queue_order(st.session_state.trial_table)
                    baseline_result = nhs_solver.solve_nhs_schedule(baseline_table, st.session_state.assumptions)
                    baseline_order = (
                        baseline_result["schedule"].sort_values("final_rank")["trial_id"].astype(str).tolist()
                    )
                moved = core.apply_manual_queue_move(
                    st.session_state.trial_table,
                    selected_trial,
                    int(target_position),
                    st.session_state.assumptions,
                    baseline_order=baseline_order,
                )
                updated_table = core.normalise_edited_trials(
                    st.session_state.trial_table, moved, st.session_state.assumptions
                )
                core.validate_manual_ranks(updated_table, st.session_state.assumptions)
                st.session_state.trial_table = updated_table
                core.mark_schedule_dirty(auto_save=True)
                result = nhs_solver.solve_nhs_schedule(st.session_state.trial_table, st.session_state.assumptions)
                st.session_state.schedule_result = result["schedule"]
                st.session_state.schedule_info = result.get("technical_info", {})
                core.mark_schedule_clean(auto_save=True)
                st.success("Manual queue move applied and the recommendation was recalculated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not apply the manual queue move: {exc}")

        if reset_order:
            try:
                updated_table = core.clear_manual_queue_order(st.session_state.trial_table)
                updated_table = core.normalise_edited_trials(
                    st.session_state.trial_table, updated_table, st.session_state.assumptions
                )
                st.session_state.trial_table = updated_table
                core.mark_schedule_dirty(auto_save=True)
                result = nhs_solver.solve_nhs_schedule(st.session_state.trial_table, st.session_state.assumptions)
                st.session_state.schedule_result = result["schedule"]
                st.session_state.schedule_info = result.get("technical_info", {})
                core.mark_schedule_clean(auto_save=True)
                st.success("Manual override cleared. The optimiser controls the order again.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not clear the manual queue override: {exc}")

core.render_page_navigation(
    previous_page="pages/05_Capacity_Planning.py",
    next_page="pages/03_Recommended_Schedule.py",
    previous_label="Capacity",
    next_label="Schedule",
)
