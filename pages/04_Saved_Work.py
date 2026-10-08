import pandas as pd
import streamlit as st

import nhs_core as core
import ui_components as ui

core.initialise_state()

st.title("Review & Save")
st.caption(
    "Review one trial at a time, record the Pharmacy decision and note, then create a checkpoint or export the updated workspace."
)

review_tab, workspace_tab, export_tab = st.tabs(["Trial review", "Workspace & backup", "Updated Excel"])

with review_tab:
    if st.session_state.trial_table is None:
        st.info("Load a workspace on **Trials** before reviewing individual trials.")
    else:
        operational = core.build_operational_view(st.session_state.trial_table, st.session_state.assumptions)
        if operational.empty:
            st.info("No trials are available to review.")
        else:
            # Use a clean schedule only. Stale recommendations are deliberately not shown as current.
            schedule = st.session_state.get("schedule_result")
            clean_schedule = schedule is not None and len(schedule) and not st.session_state.get("schedule_dirty", False)
            schedule_lookup = {}
            if clean_schedule:
                schedule = core.sync_schedule_metadata(schedule, st.session_state.trial_table)
                schedule_lookup = {
                    str(r["trial_id"]): r for _, r in schedule.iterrows()
                }
            elif schedule is not None and len(schedule):
                st.warning("Inputs changed since the last calculation. Expected completion and margin are hidden until Schedule is recalculated.")

            trial_options = operational["trial_id"].astype(str).tolist()
            selected = st.selectbox("Trial to review", trial_options, key="review_selected_trial")
            op = operational.loc[operational["trial_id"].astype(str).eq(selected)].iloc[0]
            sr = schedule_lookup.get(selected)

            completion = sr.get("completion_rec") if sr is not None else None
            margin = sr.get("margin_days") if sr is not None else None
            queue_type = sr.get("queue_type", op.get("queue_type", "")) if sr is not None else op.get("queue_type", "")
            ui.trial_summary_card(
                trial=selected,
                status=op.get("effective_trial_status", ""),
                due=op.get("due_date"),
                completion=completion,
                margin=margin,
                priority=op.get("effective_priority_score"),
                queue_type=queue_type,
            )

            left, right = st.columns([1.25, 1])
            with left:
                st.markdown("#### Recommended workstream path")
                if sr is None:
                    st.caption("Generate a clean schedule to see recommended workstream dates.")
                else:
                    rows = []
                    for label, sc, ec, rem in [
                        ("CT", "CT_start_rec", "CT_end_rec", "ct_remaining_bdays"),
                        ("Aseptic", "Aseptic_start_rec", "Aseptic_end_rec", "aseptic_remaining_bdays"),
                        ("ePMA", "ePMA_start_rec", "ePMA_end_rec", "epma_remaining_bdays"),
                    ]:
                        remaining = pd.to_numeric(sr.get(rem), errors="coerce")
                        remaining = 0 if pd.isna(remaining) else int(round(float(remaining)))
                        rows.append({
                            "Workstream": label,
                            "Status": ui.status_label("Scheduled" if remaining > 0 else "Completed / N/A"),
                            "Start": core.format_date_for_display(sr.get(sc)),
                            "End": core.format_date_for_display(sr.get(ec)),
                            "Remaining days": remaining,
                        })
                    ws = pd.DataFrame(rows)
                    st.dataframe(ui.dataframe_badge_style(ws, status_columns=["Status"]), use_container_width=True, hide_index=True)

                due_days = op.get("days_to_55_day_due")
                details = pd.DataFrame([
                    {"Field": "Due status", "Value": ui.due_label(due_days)},
                    {"Field": "CT complexity", "Value": str(op.get("ct_complexity", "Unknown"))},
                    {"Field": "ePMA complexity", "Value": str(op.get("epma_complexity", "N/A"))},
                    {"Field": "Priority source", "Value": "Mean fallback" if bool(op.get("priority_is_mean_imputed")) else "Supplied"},
                    {"Field": "Scheduling action", "Value": str(op.get("scheduling_action", ""))},
                ])
                st.dataframe(details, use_container_width=True, hide_index=True)

            with right:
                st.markdown("#### Pharmacy review")
                table = st.session_state.trial_table.copy().reset_index(drop=True)
                mask = table["trial_id"].astype(str).eq(selected)
                idx = table.index[mask][0]
                current_decision = str(table.at[idx, "final_decision"] or "")
                decision_options = list(core.FINAL_DECISION_OPTIONS)
                if current_decision not in decision_options:
                    decision_options.append(current_decision)

                with st.form("individual_trial_review_form"):
                    decision = st.selectbox(
                        "Final decision",
                        decision_options,
                        index=decision_options.index(current_decision),
                    )
                    note = st.text_area(
                        "Pharmacy Note",
                        value=str(table.at[idx, "pharmacy_note"] or ""),
                        height=170,
                        placeholder="Record the rationale, dependency, delay reason or follow-up action.",
                    )
                    save_review = st.form_submit_button("Save trial review", type="primary", use_container_width=True)

                if save_review:
                    table.at[idx, "final_decision"] = str(decision or "").strip()
                    table.at[idx, "pharmacy_note"] = str(note or "").strip()
                    st.session_state.trial_table = core.normalise_edited_trials(
                        st.session_state.trial_table, table, st.session_state.assumptions
                    )
                    if st.session_state.get("schedule_result") is not None:
                        st.session_state.schedule_result = core.sync_schedule_metadata(
                            st.session_state.schedule_result, st.session_state.trial_table
                        )
                    core.autosave_working_state()
                    st.success("Final decision and Pharmacy Note saved.")
                    st.rerun()

                c1, c2 = st.columns(2)
                if c1.button("Open Prioritise", use_container_width=True):
                    st.switch_page("pages/02_Trial_Prioritisation.py")
                if c2.button("Open Schedule", use_container_width=True):
                    st.switch_page("pages/03_Recommended_Schedule.py")

with workspace_tab:
    if st.session_state.trial_table is None:
        st.info("No current workspace is loaded. You can still restore a JSON backup below.")
    else:
        auto = st.session_state.get("_last_autosave_at")
        if auto:
            st.success(f"Current workspace auto-saved locally at {str(auto).replace('T', ' ')[:19]}.")
        else:
            st.caption("The next saved edit will create the local autosave.")
        if st.button("Save current workspace now", type="primary", use_container_width=True):
            try:
                core.autosave_working_state()
                st.success("Current workspace saved locally.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    check_tab, backup_tab, notes_tab = st.tabs(["Checkpoints", "Backup / restore", "Persistence notes"])
    with check_tab:
        st.markdown("#### Named checkpoints")
        name = st.text_input("Checkpoint name", placeholder="e.g. Before Wednesday pharmacy meeting")
        if st.button("Save named checkpoint", type="primary", disabled=st.session_state.trial_table is None):
            try:
                core.save_working_state(name)
                st.success("Checkpoint saved.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        states = core.list_saved_working_states()
        if not states:
            st.caption("No named checkpoints yet.")
        else:
            labels = {f"{x['name']} · {x['saved_at'].replace('T', ' ')[:16]}": x["file"] for x in states}
            selected_state = st.selectbox("Saved checkpoints", list(labels), key="review_saved_checkpoint")
            c1, c2 = st.columns(2)
            if c1.button("Load checkpoint", use_container_width=True):
                core.load_working_state(labels[selected_state])
                st.success("Checkpoint loaded.")
                st.rerun()
            if c2.button("Delete checkpoint", use_container_width=True):
                core.delete_saved_working_state(labels[selected_state])
                st.rerun()

    with backup_tab:
        st.markdown("#### Portable workspace backup")
        if st.session_state.trial_table is not None:
            st.download_button(
                "Download workspace backup (.json)",
                data=core.current_workspace_json_bytes(),
                file_name="pharmacy_planning_workspace.json",
                mime="application/json",
                use_container_width=True,
            )
        backup = st.file_uploader("Restore workspace backup", type=["json"], key="workspace_backup_upload")
        if backup is not None and st.button("Restore this backup", type="primary"):
            try:
                core.load_working_state_from_json_bytes(backup.getvalue())
                st.success("Workspace restored.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not restore backup: {exc}")

    with notes_tab:
        st.write(
            "Saved edits include trial data, Pharmacy Notes, final decisions, manual ranks, assumptions, resource-availability periods and the current schedule."
        )
        st.warning(
            "Local Streamlit storage is suitable for a prototype, not a production audit database. A real deployment should use approved authenticated persistent storage and an audit trail."
        )

with export_tab:
    st.markdown("#### Download the updated trial workbook")
    st.caption(
        "The workbook retains editable trial status, complexity, priority, manual rank, final decision and Pharmacy Note, plus resource availability and assumptions."
    )
    if st.session_state.trial_table is None:
        st.info("Load a workspace first.")
    else:
        st.download_button(
            "Download updated trial workbook (.xlsx)",
            data=core.current_trial_workbook_bytes(),
            file_name="pharmacy_trials_updated.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

core.render_page_navigation(
    previous_page="pages/03_Recommended_Schedule.py",
    next_page="pages/01_Portfolio_Overview.py",
    previous_label="Schedule",
    next_label="Overview",
)
