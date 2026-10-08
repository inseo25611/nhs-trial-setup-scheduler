import io

import pandas as pd
import streamlit as st

import nhs_core as core
import ui_components as ui

core.initialise_state()

EPMA_OPTIONS = ["", "chemo ePMA", "inpatient ePMA", "none"]
ASEPTIC_OPTIONS = ["Unknown", "Yes", "No"]
STATUS_OPTIONS = ["", core.STATUS_NOT_STARTED, core.STATUS_COMPLETED]

st.title("Trials & Data Quality")
st.caption(
    "Load, map and maintain the Pharmacy trial list. Column positions, sheet names, header rows and portfolio size are not fixed."
)

upload_tab, editor_tab, quality_tab = st.tabs(["Upload & mapping", "Trial editor", "Data quality"])

# ============================================================
# TAB 1 — FLEXIBLE UPLOAD + MAPPING
# ============================================================
with upload_tab:
    st.markdown("#### Load a workbook")
    st.caption(
        "The app first detects the most likely sheet/header and matches recognised column names. "
        "Uncertain matches are shown for staff confirmation rather than guessed silently."
    )

    st.caption("No file to hand? Load 20 fictitious trials instead:")
    core.render_sample_data_button(key="trials_sample")

    uploaded_file = st.file_uploader(
        "Clinical trial workbook",
        type=["xlsx", "csv"],
        key="flexible_operational_upload",
    )

    c1, c2 = st.columns([1, 3])
    with c1:
        inspect_clicked = st.button(
            "Inspect workbook",
            type="primary",
            use_container_width=True,
            disabled=uploaded_file is None,
        )
    with c2:
        if st.session_state.uploaded_tracker_name:
            st.caption(
                f"Current workspace: **{st.session_state.uploaded_tracker_name}** · "
                f"{len(st.session_state.trial_table) if st.session_state.trial_table is not None else 0} trial(s)"
            )

    if inspect_clicked and uploaded_file is not None:
        try:
            raw, info = core.inspect_operational_file(uploaded_file)
            st.session_state.pending_raw_df = raw
            st.session_state.pending_import_info = info
            st.session_state.pending_filename = uploaded_file.name
        except Exception as exc:
            st.error(f"Could not inspect the file: {exc}")

    pending = st.session_state.get("pending_raw_df")
    info = st.session_state.get("pending_import_info") or {}

    if pending is not None:
        st.success(
            f"Detected sheet **{info.get('sheet_name')}**, header row **{info.get('header_row_excel')}**. "
            f"Found {len(pending)} raw row(s) before trial-row filtering."
        )

        mapping_summary, detected, suggestions = core.mapping_summary(pending)
        st.dataframe(mapping_summary, use_container_width=True, hide_index=True)

        with st.expander("Review / change detected layout", expanded=False):
            st.caption(
                "Use this only if the automatic sheet or header row is wrong. Header row uses the Excel/CSV row number starting at 1."
            )
            sheet_names = info.get("sheet_names", [info.get("sheet_name", "CSV")])
            current_sheet = info.get("sheet_name")
            selected_sheet = st.selectbox(
                "Sheet",
                sheet_names,
                index=sheet_names.index(current_sheet) if current_sheet in sheet_names else 0,
                disabled=(sheet_names == ["CSV"]),
            )
            selected_header_excel = st.number_input(
                "Header row",
                min_value=1,
                max_value=100,
                value=int(info.get("header_row_excel", 1)),
                step=1,
            )
            if st.button("Re-read using this layout"):
                if uploaded_file is None:
                    st.error("Keep the source file selected above while changing its layout.")
                else:
                    try:
                        raw, new_info = core.inspect_operational_file(
                            uploaded_file,
                            sheet_name=None if selected_sheet == "CSV" else selected_sheet,
                            header_row=int(selected_header_excel) - 1,
                        )
                        st.session_state.pending_raw_df = raw
                        st.session_state.pending_import_info = new_info
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        st.markdown("#### Confirm column mapping")
        st.caption(
            "Exact recognised names are preselected. A fuzzy suggestion is shown only as guidance and is not applied until you choose it. "
            "‘Not supplied’ means no source column is mapped to that field; it does NOT mean that the column exists but its cells are blank. "
            "A mapped CT/ePMA Complexity column may contain blank cells — those cells are loaded as Unknown and use the upper-bound duration."
        )

        source_columns = [str(c) for c in pending.columns]
        not_supplied = "— Not supplied —"
        mapping_fields = [
            "trial_id", "hra_approval", "site_selected", "pharmacy_notified",
            "pharmacy_setup_start", "aseptic_notify", "aseptic_bmr_authorised",
            "iqemo_setup", "iqemo_authorised", "greenlight",
            "aseptic_flag", "prescribing_system", "ct_complexity", "epma_complexity",
            "priority_score", "trial_status", "final_decision", "pharmacy_note",
            "site_confirmed", "trial_phase", "q4b", "manual_rank",
        ]

        confirmed_mapping = {}
        with st.form("column_mapping_form"):
            left, right = st.columns(2)
            for i, field in enumerate(mapping_fields):
                host = left if i % 2 == 0 else right
                exact = detected.get(field)
                suggested = (suggestions.get(field) or {}).get("column")
                options = [not_supplied] + source_columns
                if exact in source_columns:
                    default = exact
                else:
                    # Do not silently accept fuzzy matches.
                    default = not_supplied
                with host:
                    selected = st.selectbox(
                        core.FIELD_LABELS.get(field, field),
                        options,
                        index=options.index(default),
                        key=f"mapping_{field}_{st.session_state.get('pending_filename','source')}",
                        help=(f"Possible match: {suggested}" if suggested and not exact else None),
                    )
                    confirmed_mapping[field] = None if selected == not_supplied else selected

            load_clicked = st.form_submit_button(
                "Confirm mapping & load trials",
                type="primary",
                use_container_width=True,
            )

        if load_clicked:
            if not confirmed_mapping.get("trial_id"):
                st.error("Confirm the column containing the trial name. This is the only field required to construct the table.")
            else:
                try:
                    pending.attrs["column_mapping"] = confirmed_mapping
                    table = core.build_operational_trial_table(
                        pending,
                        st.session_state.assumptions,
                        mapping=confirmed_mapping,
                    )
                    st.session_state.raw_df = pending
                    st.session_state.trial_table = table
                    st.session_state.uploaded_tracker_name = st.session_state.get("pending_filename", "uploaded file")
                    st.session_state.uploaded_source_type = info.get("source_type", "operational workbook")
                    st.session_state.source_mapping = confirmed_mapping
                    st.session_state.source_layout = {
                        "sheet_name": info.get("sheet_name"),
                        "header_row_excel": info.get("header_row_excel"),
                    }
                    st.session_state.schedule_result = None
                    st.session_state.schedule_info = None
                    st.session_state.trial_editor_version += 1
                    core.mark_schedule_dirty(auto_save=True)
                    st.success(f"Loaded {len(table)} trial(s).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not load the mapped data: {exc}")

        with st.expander("Why a field may show 'Not supplied'", expanded=False):
            st.write(
                "**Not supplied means the app has not mapped a workbook column to that field.** If the column is mapped but some cells are blank, "
                "the column name still appears in the mapping. Blank CT/ePMA complexity cells become **Unknown** and use the Complex-tier upper bound (30 working days). "
                "Missing solver-critical dates/routes are loaded but flagged under Data quality so Pharmacy can complete them in the app."
            )

    if st.session_state.trial_table is not None:
        if st.button("Start a new empty session", help="Clears the current local workspace and autosave."):
            core.clear_autosave()
            for key in [
                "raw_df", "trial_table", "uploaded_tracker_name", "uploaded_source_type",
                "source_mapping", "source_layout", "schedule_result", "schedule_info",
                "pending_raw_df", "pending_import_info", "pending_filename",
            ]:
                st.session_state[key] = None if key not in {"source_mapping", "source_layout"} else {}
            st.session_state.schedule_dirty = False
            st.rerun()


# ============================================================
# TAB 2 — EDITABLE TRIAL TABLE
# ============================================================
with editor_tab:
    if st.session_state.trial_table is None:
        st.info("Load a workbook on **Upload & mapping** first.")
    else:
        table = st.session_state.trial_table.copy().reset_index(drop=True)
        operational = core.build_operational_view(table, st.session_state.assumptions)

        st.markdown("#### Maintain the trial list")
        st.caption(
            "Operational status is derived automatically from existing tracker milestones. "
            "Pharmacy Green Light archives the whole trial; Aseptic BMR authorisation completes the Aseptic branch; "
            "iQemo authorisation completes the ePMA branch. These dates are reused rather than asking staff to maintain a separate progress status."
        )

        editor_cols = [
            "trial_id", "hra_date", "site_date", "pharmacy_notified_date",
            "pharmacy_setup_start_date", "aseptic_notify_date", "aseptic_bmr_authorised_date",
            "iqemo_setup_date", "iqemo_authorised_date", "greenlight_date",
            "aseptic_required", "prescribing_system", "ct_complexity", "epma_complexity",
            "priority_score", "final_decision", "pharmacy_note",
        ]
        editor = table[editor_cols].copy()
        decision_options = list(core.FINAL_DECISION_OPTIONS)
        for value in editor["final_decision"].fillna("").astype(str):
            if value not in decision_options:
                decision_options.append(value)

        with st.form("trial_editor_form"):
            edited = st.data_editor(
                editor,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "trial_id": st.column_config.TextColumn("Trial", width="large"),
                    "hra_date": st.column_config.DateColumn("HRA approval", format="DD/MM/YYYY"),
                    "site_date": st.column_config.DateColumn("Site selected", format="DD/MM/YYYY"),
                    "pharmacy_notified_date": st.column_config.DateColumn("Pharmacy notified", format="DD/MM/YYYY"),
                    "pharmacy_setup_start_date": st.column_config.DateColumn("Pharmacy set-up start", format="DD/MM/YYYY"),
                    "aseptic_notify_date": st.column_config.DateColumn("Aseptic notified", format="DD/MM/YYYY"),
                    "aseptic_bmr_authorised_date": st.column_config.DateColumn("Aseptic BMR authorised", format="DD/MM/YYYY"),
                    "iqemo_setup_date": st.column_config.DateColumn("iQemo template set up", format="DD/MM/YYYY"),
                    "iqemo_authorised_date": st.column_config.DateColumn("iQemo template authorised", format="DD/MM/YYYY"),
                    "greenlight_date": st.column_config.DateColumn("Pharmacy Green Light", format="DD/MM/YYYY"),
                    "aseptic_required": st.column_config.SelectboxColumn("Aseptic", options=ASEPTIC_OPTIONS),
                    "prescribing_system": st.column_config.SelectboxColumn(
                        "Prescribing system", options=EPMA_OPTIONS,
                        help="chemo ePMA / inpatient ePMA require the ePMA workstream; none means no ePMA."
                    ),
                    "ct_complexity": st.column_config.SelectboxColumn(
                        "CT Complexity", options=core.COMPLEXITY_OPTIONS,
                        help="Blank/Unknown uses the Complex-tier upper bound (30 working days).",
                    ),
                    "epma_complexity": st.column_config.SelectboxColumn(
                        "ePMA Complexity", options=["N/A"] + core.COMPLEXITY_OPTIONS,
                        help="For ePMA-required trials, blank/Unknown uses 30 working days.",
                    ),
                    "priority_score": st.column_config.NumberColumn("Priority", min_value=0.0, max_value=100.0),
                    "final_decision": st.column_config.SelectboxColumn(
                        "Final decision", options=decision_options, width="medium"
                    ),
                    "pharmacy_note": st.column_config.TextColumn("Pharmacy Note", width="large"),
                },
                key=f"trial_editor_{st.session_state.trial_editor_version}",
            )
            save_edits = st.form_submit_button("Save trial changes", type="primary", use_container_width=True)

        if save_edits:
            proposed = table.copy()
            for col in editor_cols:
                proposed[col] = edited[col].values
            try:
                updated = core.normalise_edited_trials(table, proposed, st.session_state.assumptions)
                if updated["trial_id"].astype(str).str.strip().duplicated().any():
                    raise ValueError("Trial names must be unique.")
                st.session_state.trial_table = updated.reset_index(drop=True)
                st.session_state.trial_editor_version += 1
                core.mark_schedule_dirty(auto_save=True)
                st.success("Trial changes saved and auto-saved locally.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        with st.expander("Add a trial", expanded=False):
            with st.form("add_trial_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    name = st.text_input("Trial name *")
                    priority_text = st.text_input("Priority", placeholder="Blank = cohort mean / equal fallback")
                    st.caption("Status will be derived automatically from milestones.")
                with c2:
                    hra = st.date_input("HRA approval", value=None, format="DD/MM/YYYY")
                    site = st.date_input("Site selected", value=None, format="DD/MM/YYYY")
                    notified = st.date_input("Pharmacy notified", value=None, format="DD/MM/YYYY")
                with c3:
                    aseptic = st.selectbox("Aseptic", ASEPTIC_OPTIONS)
                    system = st.selectbox("Prescribing system", EPMA_OPTIONS)
                    ct_comp = st.selectbox("CT Complexity", core.COMPLEXITY_OPTIONS)
                    epma_comp = st.selectbox("ePMA Complexity", core.COMPLEXITY_OPTIONS)
                note = st.text_area("Pharmacy Note")
                add = st.form_submit_button("Add trial", type="primary")
            if add:
                clean_name = str(name).strip()
                if not clean_name:
                    st.error("Trial name is required.")
                elif clean_name.lower() in set(table["trial_id"].astype(str).str.strip().str.lower()):
                    st.error("That trial name already exists.")
                else:
                    try:
                        priority_value = float(priority_text) if str(priority_text).strip() else None
                        if priority_value is not None and priority_value <= 0:
                            priority_value = None
                    except Exception:
                        st.error("Priority must be a number or left blank.")
                        priority_value = "INVALID"

                    if priority_value != "INVALID":
                        row = core.blank_trial_row(st.session_state.assumptions)
                        row.update({
                            "trial_id": clean_name,
                            "hra_date": hra,
                            "site_date": site,
                            "pharmacy_notified_date": notified,
                            "aseptic_required": aseptic,
                            "prescribing_system": system,
                            "ct_complexity": ct_comp,
                            "epma_complexity": epma_comp,
                            "priority_score": priority_value,
                            "pharmacy_note": note,
                        })
                        new_table = pd.concat([table, pd.DataFrame([row])], ignore_index=True)
                        st.session_state.trial_table = core.normalise_edited_trials(table, new_table, st.session_state.assumptions)
                        st.session_state.trial_editor_version += 1
                        core.mark_schedule_dirty(auto_save=True)
                        st.rerun()

        with st.expander("Aseptic duration overrides", expanded=False):
            st.caption(
                "Aseptic uses the default 30-working-day active-case window. Enter an override only where Pharmacy has better trial-specific information."
            )
            a_trials = table[table["aseptic_required"].eq("Yes")].copy()
            if a_trials.empty:
                st.caption("No trials currently require Aseptic Services.")
            else:
                aedit = pd.DataFrame({
                    "Trial": a_trials["trial_id"].astype(str),
                    "Override (working days)": pd.to_numeric(a_trials["aseptic_duration_override_bdays"], errors="coerce"),
                })
                with st.form("aseptic_override_form"):
                    aedited = st.data_editor(
                        aedit,
                        use_container_width=True,
                        hide_index=True,
                        disabled=["Trial"],
                        column_config={
                            "Override (working days)": st.column_config.NumberColumn(min_value=1, max_value=365)
                        },
                    )
                    save_a = st.form_submit_button("Save Aseptic overrides")
                if save_a:
                    proposed = table.copy()
                    for _, r in aedited.iterrows():
                        mask = proposed["trial_id"].astype(str).eq(str(r["Trial"]))
                        if mask.any():
                            proposed.loc[mask, "aseptic_duration_override_bdays"] = r["Override (working days)"]
                    st.session_state.trial_table = core.normalise_edited_trials(table, proposed, st.session_state.assumptions)
                    st.session_state.trial_editor_version += 1
                    core.mark_schedule_dirty(auto_save=True)
                    st.rerun()

        with st.expander("Remove a trial", expanded=False):
            remove_trial = st.selectbox("Trial to remove", table["trial_id"].astype(str).tolist())
            if st.button("Remove selected trial"):
                st.session_state.trial_table = table.loc[~table["trial_id"].astype(str).eq(remove_trial)].reset_index(drop=True)
                st.session_state.trial_editor_version += 1
                core.mark_schedule_dirty(auto_save=True)
                st.rerun()

        with st.expander("Derived planning fields", expanded=False):
            derived_cols = [
                "trial_id", "effective_trial_status", "queue_type", "clock_start", "pharmacy_notified_date", "due_date",
                "ct_progress_status", "ct_duration_bdays", "ct_remaining_bdays",
                "aseptic_progress_status", "aseptic_duration_bdays", "aseptic_remaining_bdays",
                "epma_progress_status", "epma_complexity", "epma_duration_bdays", "epma_remaining_bdays",
                "snapshot_category", "scheduling_action",
            ]
            dv = operational[[c for c in derived_cols if c in operational.columns]].rename(columns={
                "trial_id": "Trial", "effective_trial_status": "Effective status", "queue_type": "Queue type",
                "clock_start": "55-day clock start", "pharmacy_notified_date": "Pharmacy notified",
                "due_date": "55-day due",
                "ct_progress_status": "CT progress", "ct_duration_bdays": "CT full days", "ct_remaining_bdays": "CT planning allowance",
                "aseptic_progress_status": "Aseptic progress", "aseptic_duration_bdays": "Aseptic full days", "aseptic_remaining_bdays": "Aseptic remaining",
                "epma_progress_status": "ePMA progress", "epma_complexity": "ePMA Complexity",
                "epma_duration_bdays": "ePMA full days", "epma_remaining_bdays": "ePMA remaining",
                "snapshot_category": "Portfolio position", "scheduling_action": "Scheduling action",
            })
            dv = core.dates_as_date_objects(dv, ["55-day clock start", "Pharmacy notified", "55-day due"])
            st.dataframe(
                dv, use_container_width=True, hide_index=True,
                column_config={
                    "55-day clock start": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Pharmacy notified": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "55-day due": st.column_config.DateColumn(format="DD/MM/YYYY"),
                },
            )


# ============================================================
# TAB 3 — DATA QUALITY + SCHEDULING ELIGIBILITY
# ============================================================
with quality_tab:
    if st.session_state.trial_table is None:
        st.info("Load a workbook first.")
    else:
        derived = core.build_operational_view(st.session_state.trial_table, st.session_state.assumptions)
        completed = derived["effective_trial_status"].eq(core.STATUS_COMPLETED)
        ready = derived["model_ready"].fillna(False).astype(bool)
        awaiting = derived["awaiting_pharmacy_notification"].fillna(False).astype(bool)
        not_stage2 = derived["not_yet_stage2_started"].fillna(False).astype(bool)
        needs_data = derived["needs_data_attention"].fillna(False).astype(bool)
        no_work = derived.get("no_modelled_work_remaining", pd.Series(False, index=derived.index)).fillna(False).astype(bool)
        escalation = derived["escalation_needed"].fillna(False).astype(bool) & ~completed

        m1, m2, m3, m4 = st.columns(4)
        ui.metric_card(m1, "Scheduling queue", int(ready.sum()), tone="primary")
        ui.metric_card(m2, "Completed / archived", int(completed.sum()), tone="success")
        ui.metric_card(m3, "Awaiting Pharmacy", int(awaiting.sum()), tone="warning")
        ui.metric_card(m4, "Needs data", int(needs_data.sum()), tone="danger" if needs_data.any() else "success")
        ui.mini_stats([("Final completion review", int(no_work.sum())), ("Escalation flags", int(escalation.sum())), ("Not yet Stage 2", int(not_stage2.sum()))])

        st.markdown("#### Workstream progress inferred from tracker milestones")
        st.caption(
            "No separate progress-status field is required. BMR authorisation completes Aseptic; iQemo authorisation completes ePMA; "
            "Pharmacy Green Light completes and archives the whole trial. Future-dated milestones are ignored. "
            "CT start is recognised from Pharmacy set-up start, but elapsed time is not used to infer CT completion because no dedicated CT-completion milestone is available."
        )
        progress_cols = [
            "trial_id", "effective_trial_status", "snapshot_category",
            "ct_progress_status", "ct_remaining_bdays",
            "aseptic_progress_status", "aseptic_remaining_bdays",
            "epma_progress_status", "epma_remaining_bdays",
            "scheduling_action",
        ]
        progress = derived[[c for c in progress_cols if c in derived.columns]].rename(columns={
            "trial_id": "Trial",
            "effective_trial_status": "Overall status",
            "snapshot_category": "Portfolio position",
            "ct_progress_status": "CT progress",
            "ct_remaining_bdays": "CT planning allowance",
            "aseptic_progress_status": "Aseptic progress",
            "aseptic_remaining_bdays": "Aseptic remaining",
            "epma_progress_status": "ePMA progress",
            "epma_remaining_bdays": "ePMA remaining",
            "scheduling_action": "Scheduling action",
        })
        for col in ["Overall status", "CT progress", "Aseptic progress", "ePMA progress"]:
            if col in progress.columns:
                progress[col] = progress[col].map(ui.status_label)
        st.dataframe(
            ui.dataframe_badge_style(progress, status_columns=["Overall status", "CT progress", "Aseptic progress", "ePMA progress"]),
            use_container_width=True,
            hide_index=True,
        )

        excluded = derived.loc[~ready].copy()
        st.markdown("#### Excluded / not currently scheduled")
        if excluded.empty:
            st.success("Every loaded trial is currently eligible for scheduling.")
        else:
            st.info(
                "The rows below are not sent to the optimiser at this planning date. "
                "The reason is retained explicitly so completed trials are not confused with data-quality blocks."
            )
            excluded_cols = [
                "trial_id", "effective_trial_status", "snapshot_category",
                "missing_required_input", "scheduling_action", "scheduling_block_reason",
                "observed_greenlight", "pharmacy_note",
            ]
            ex = excluded[[c for c in excluded_cols if c in excluded.columns]].rename(columns={
                "trial_id": "Trial",
                "effective_trial_status": "Status",
                "snapshot_category": "Portfolio position",
                "missing_required_input": "Missing input",
                "scheduling_action": "Scheduling action",
                "scheduling_block_reason": "Why excluded",
                "observed_greenlight": "Pharmacy Green Light",
                "pharmacy_note": "Pharmacy Note",
            })
            if "Pharmacy Green Light" in ex.columns:
                ex = core.dates_as_date_objects(ex, ["Pharmacy Green Light"])
            st.dataframe(
                ex,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Pharmacy Green Light": st.column_config.DateColumn(format="DD/MM/YYYY")
                } if "Pharmacy Green Light" in ex.columns else None,
            )

        if completed.any():
            with st.expander("✅ Completed / archived trials — excluded from future scheduling", expanded=True):
                cv = derived.loc[completed, [
                    "trial_id", "observed_greenlight", "ct_progress_status",
                    "aseptic_progress_status", "epma_progress_status", "scheduling_block_reason",
                ]].rename(columns={
                    "trial_id": "Trial",
                    "observed_greenlight": "Pharmacy Green Light",
                    "ct_progress_status": "CT",
                    "aseptic_progress_status": "Aseptic",
                    "epma_progress_status": "ePMA",
                    "scheduling_block_reason": "Reason",
                })
                cv = core.dates_as_date_objects(cv, ["Pharmacy Green Light"])
                st.dataframe(
                    cv,
                    use_container_width=True,
                    hide_index=True,
                    column_config={"Pharmacy Green Light": st.column_config.DateColumn(format="DD/MM/YYYY")},
                )

        if awaiting.any():
            with st.expander("🟠 Stage 2 active, awaiting Pharmacy notification", expanded=False):
                av = derived.loc[awaiting, [
                    "trial_id", "clock_start", "pharmacy_notified_date", "due_date", "scheduling_block_reason"
                ]]
                av = av.rename(columns={
                    "clock_start": "55-day clock start", "pharmacy_notified_date": "Pharmacy notified",
                    "due_date": "55-day due", "trial_id": "Trial", "scheduling_block_reason": "Why excluded",
                })
                av = core.dates_as_date_objects(av, ["55-day clock start", "Pharmacy notified", "55-day due"])
                st.dataframe(av, use_container_width=True, hide_index=True, column_config={
                    "55-day clock start": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Pharmacy notified": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "55-day due": st.column_config.DateColumn(format="DD/MM/YYYY"),
                })

        if needs_data.any():
            with st.expander("🔴 Needs data before scheduling", expanded=False):
                problem = derived.loc[needs_data, [
                    "trial_id", "missing_required_input", "scheduling_block_reason", "pharmacy_note"
                ]].rename(columns={
                    "trial_id": "Trial",
                    "missing_required_input": "Missing input",
                    "scheduling_block_reason": "Why excluded",
                    "pharmacy_note": "Pharmacy Note",
                })
                st.dataframe(problem, use_container_width=True, hide_index=True)

        if not_stage2.any():
            with st.expander("⚪ Not yet Stage 2 started", expanded=False):
                nv = derived.loc[not_stage2, ["trial_id", "clock_start", "scheduling_block_reason"]]
                nv = nv.rename(columns={
                    "clock_start": "55-day clock start", "trial_id": "Trial",
                    "scheduling_block_reason": "Why excluded",
                })
                nv = core.dates_as_date_objects(nv, ["55-day clock start"])
                st.dataframe(
                    nv, use_container_width=True, hide_index=True,
                    column_config={"55-day clock start": st.column_config.DateColumn(format="DD/MM/YYYY")},
                )

        if no_work.any():
            with st.expander("🟢 No modelled work remaining — final completion review", expanded=False):
                nw = derived.loc[no_work, [
                    "trial_id", "ct_progress_status", "aseptic_progress_status",
                    "epma_progress_status", "scheduling_block_reason",
                ]].rename(columns={
                    "trial_id": "Trial", "ct_progress_status": "CT",
                    "aseptic_progress_status": "Aseptic", "epma_progress_status": "ePMA",
                    "scheduling_block_reason": "Why excluded",
                })
                st.dataframe(nw, use_container_width=True, hide_index=True)

        if escalation.any():
            with st.expander("🟠 Overdue escalation flags — lateness alone does not exclude a trial", expanded=False):
                ev = derived.loc[escalation, [
                    "trial_id", "overdue_days", "due_date", "effective_trial_status", "model_ready", "scheduling_action"
                ]]
                ev = ev.rename(columns={
                    "trial_id": "Trial", "overdue_days": "Overdue days", "due_date": "55-day due",
                    "effective_trial_status": "Status", "model_ready": "In optimiser",
                    "scheduling_action": "Scheduling action",
                })
                ev = core.dates_as_date_objects(ev, ["55-day due"])
                st.dataframe(
                    ev,
                    use_container_width=True,
                    hide_index=True,
                    column_config={"55-day due": st.column_config.DateColumn(format="DD/MM/YYYY")},
                )

        if st.session_state.source_mapping:
            with st.expander("Current source mapping", expanded=False):
                mapping_rows = [
                    {"App field": core.FIELD_LABELS.get(k, k), "Source column": v or "Not supplied"}
                    for k, v in st.session_state.source_mapping.items()
                ]
                st.dataframe(pd.DataFrame(mapping_rows), use_container_width=True, hide_index=True)


core.render_page_navigation(
    previous_page="pages/01_Portfolio_Overview.py",
    next_page="pages/05_Capacity_Planning.py",
    previous_label="Overview",
    next_label="Capacity",
)
