import copy

import pandas as pd
import streamlit as st

import nhs_core as core
import ui_components as ui

core.initialise_state()

st.title("Capacity & Assumptions")
st.caption(
    "Set the planning date, baseline capacities, CT-to-specialist handoff and temporary staff availability. "
    "Changes here invalidate the existing schedule until it is recalculated."
)

a = copy.deepcopy(st.session_state.assumptions)

ui.mini_stats([
    ("Planning date", pd.Timestamp(a.get("planning_date", core.DEFAULT_PLANNING_DATE)).strftime("%d %b %Y")),
    ("CT capacity", int(a.get("cap_ct", 3))),
    ("Aseptic capacity", int(a.get("cap_aseptic", 2))),
    ("ePMA capacity", int(a.get("cap_epma", 1))),
    ("CT → specialist handoff", f"{int(a.get('specialist_handoff_bdays', 2))} working days"),
])

core_tab, resource_tab, advanced_tab = st.tabs(["Core planning", "Resource availability", "Workflow & advanced"])

with core_tab:
    with st.form("core_assumptions_form"):
        st.markdown("#### Planning date and baseline capacity")
        c1, c2 = st.columns([1, 2])
        with c1:
            planning_date = st.date_input(
                "Planning date",
                value=pd.Timestamp(a.get("planning_date", core.DEFAULT_PLANNING_DATE)).date(),
                format="DD/MM/YYYY",
                help="Defaults to today. Change this manually for a historical snapshot such as the Chapter 6 demonstration.",
            )
            target_days = st.number_input(
                "Internal planning target (calendar days)",
                min_value=1,
                max_value=365,
                value=int(a.get("target_days", 55)),
                step=1,
            )
        with c2:
            r1, r2, r3 = st.columns(3)
            with r1:
                cap_ct = st.number_input("CT capacity", min_value=1, max_value=50, value=int(a.get("cap_ct", 3)), step=1)
            with r2:
                cap_aseptic = st.number_input("Aseptic capacity", min_value=1, max_value=50, value=int(a.get("cap_aseptic", 2)), step=1)
            with r3:
                cap_epma = st.number_input("ePMA capacity", min_value=1, max_value=50, value=int(a.get("cap_epma", 1)), step=1)

        st.markdown("#### Processing-time assumptions")
        st.caption(
            "CT and ePMA use the upper bound of the selected complexity tier. Blank/Unknown complexity therefore uses the Complex-tier upper bound. "
            "At each planning run, recorded progress is applied first: BMR-authorised Aseptic and iQemo-authorised ePMA branches contribute 0 future days. "
            "For CT, Pharmacy set-up start confirms that work has begun, but elapsed time is not used to infer completion; the selected CT duration is retained as a conservative planning allowance until whole-trial completion."
        )
        duration_rows = []
        for team in ["CT", "ePMA"]:
            duration_rows.append({
                "Workstream": team,
                "Simple upper": int(a["duration_tiers"][team]["Simple"][1]),
                "Moderate upper": int(a["duration_tiers"][team]["Moderate"][1]),
                "Complex upper": int(a["duration_tiers"][team]["Complex"][1]),
            })
        duration_df = pd.DataFrame(duration_rows)
        edited_duration = st.data_editor(
            duration_df,
            use_container_width=True,
            hide_index=True,
            disabled=["Workstream"],
            column_config={
                "Simple upper": st.column_config.NumberColumn(min_value=1, max_value=365),
                "Moderate upper": st.column_config.NumberColumn(min_value=1, max_value=365),
                "Complex upper": st.column_config.NumberColumn(min_value=1, max_value=365),
            },
        )
        aseptic_default = st.number_input(
            "Aseptic default active-case window (working days)",
            min_value=1,
            max_value=365,
            value=int(a.get("aseptic_default_bdays", 30)),
        )

        save_core = st.form_submit_button("Save core assumptions", type="primary", use_container_width=True)

    if save_core:
        new_a = copy.deepcopy(st.session_state.assumptions)
        new_a.update({
            "planning_date": planning_date,
            "target_days": int(target_days),
            "cap_ct": int(cap_ct),
            "cap_aseptic": int(cap_aseptic),
            "cap_epma": int(cap_epma),
            "aseptic_default_bdays": int(aseptic_default),
        })
        for _, row in edited_duration.iterrows():
            team = str(row["Workstream"])
            # Preserve lower bounds but update upper bounds. Upper-bound-only is the operational duration used.
            for tier, col in [("Simple", "Simple upper"), ("Moderate", "Moderate upper"), ("Complex", "Complex upper")]:
                lo = int(new_a["duration_tiers"][team][tier][0])
                hi = int(row[col])
                new_a["duration_tiers"][team][tier] = (min(lo, hi), hi)

        # Capacity exceptions are stored as available capacity; revalidate them when base capacities change.
        try:
            new_a["capacity_exceptions"] = core.normalise_capacity_exceptions(
                new_a.get("capacity_exceptions", []), new_a
            )
            st.session_state.assumptions = new_a
            if st.session_state.trial_table is not None:
                st.session_state.trial_table = core.normalise_edited_trials(
                    st.session_state.trial_table,
                    st.session_state.trial_table,
                    new_a,
                )
            core.mark_schedule_dirty(auto_save=True)
            st.success("Core assumptions saved and trial durations refreshed.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

with resource_tab:
    st.markdown("#### Temporary reduced capacity")
    st.caption(
        "Use this for annual leave, sickness, training or another period when fewer staff are available. "
        "Outside the entered dates, the baseline capacity above applies automatically."
    )

    existing = st.session_state.assumptions.get("capacity_exceptions", [])
    if existing:
        resource_df = pd.DataFrame(existing).rename(columns={
            "workstream": "Workstream",
            "start_date": "From",
            "end_date": "To",
            "available_capacity": "Available capacity",
            "note": "Reason",
        })
    else:
        resource_df = pd.DataFrame(columns=["Workstream", "From", "To", "Available capacity", "Reason"])

    with st.form("resource_availability_form"):
        edited_resources = st.data_editor(
            resource_df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "Workstream": st.column_config.SelectboxColumn(
                    "Workstream", options=["CT", "Aseptic", "ePMA"], required=True
                ),
                "From": st.column_config.DateColumn("From", format="DD/MM/YYYY", required=True),
                "To": st.column_config.DateColumn("To", format="DD/MM/YYYY", required=True),
                "Available capacity": st.column_config.NumberColumn(
                    "Available capacity", min_value=0, max_value=50, step=1, required=True,
                    help="Set 0 when nobody from that workstream is available. For CT capacity 3 with one person absent, enter 2."
                ),
                "Reason": st.column_config.TextColumn("Reason", width="large"),
            },
        )
        save_resources = st.form_submit_button("Save resource availability", type="primary", use_container_width=True)

    if save_resources:
        try:
            records = edited_resources.to_dict(orient="records")
            cleaned = core.normalise_capacity_exceptions(records, st.session_state.assumptions)
            st.session_state.assumptions["capacity_exceptions"] = cleaned
            core.mark_schedule_dirty(auto_save=True)
            st.success("Temporary capacity changes saved. Recalculate the schedule to apply them.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    with st.expander("How this affects the solver", expanded=False):
        st.write(
            "A temporary availability row reduces the usable concurrent capacity only for the specified business-day window. "
            "For example, ePMA capacity 1 with Available capacity 0 for five working days blocks ePMA work during that period; CT and Aseptic are unaffected."
        )

with advanced_tab:
    with st.form("advanced_assumptions_form"):
        st.markdown("#### Workflow timing & advanced settings")
        capacity_mode_labels = {
            "Continuous oversight — hold CT capacity until trial completion": "continuous",
            "CT active work only — release CT capacity after CT processing": "ct_own_duration_only",
        }
        current_mode = str(a.get("ct_capacity_mode", "continuous"))
        current_label = next(
            (label for label, value in capacity_mode_labels.items() if value == current_mode),
            next(iter(capacity_mode_labels)),
        )
        ct_capacity_label = st.selectbox(
            "CT capacity accounting",
            list(capacity_mode_labels.keys()),
            index=list(capacity_mode_labels.keys()).index(current_label),
            help=(
                "Continuous oversight is the conservative baseline: the model holds one CT capacity unit until all required workstreams finish. "
                "Operationally, continued CT involvement is known to occur, but whether it consumes a full capacity unit throughout is not quantified; this is therefore an explicit conservative modelling assumption. "
                "CT active work only releases the slot when the modelled CT planning allowance ends."
            ),
        )
        handoff = st.number_input(
            "CT → specialist handoff (working days)",
            min_value=0,
            max_value=60,
            value=int(a.get("specialist_handoff_bdays", 2)),
            step=1,
            help=(
                "Default = 2 working days. Aseptic and ePMA may start once this handoff has elapsed from the CT start date; "
                "they do not have to wait for CT to finish and may run in parallel with each other and with ongoing CT work."
            ),
        )
        horizon = st.number_input(
            "Requested planning horizon (working days)",
            min_value=30,
            max_value=1500,
            value=int(a.get("horizon_bdays", 250)),
            step=10,
            help="The solver can extend this automatically if needed for feasibility.",
        )
        escalation = st.number_input(
            "Overdue escalation threshold (calendar days)",
            min_value=1,
            max_value=1000,
            value=int(a.get("max_overdue_days", 180)),
            step=10,
            help="This is a warning threshold only. It does not remove a trial from scheduling.",
        )
        time_limit = st.number_input(
            "Solver time limit per optimisation step (seconds)",
            min_value=5,
            max_value=300,
            value=int(a.get("solver_time_limit_seconds", 60)),
            step=5,
            help=(
                "Operational scheduling runs use one CP-SAT search worker with a fixed seed, then canonicalise the "
                "Step-2 incumbent so repeated runs with identical inputs return a stable representative schedule. "
                "A longer limit can improve the Step-2 incumbent/gap but does not change the reproducibility rule."
            ),
        )
        save_advanced = st.form_submit_button("Save advanced settings", type="primary", use_container_width=True)

    if save_advanced:
        st.session_state.assumptions.update({
            "ct_capacity_mode": capacity_mode_labels[ct_capacity_label],
            "specialist_handoff_bdays": int(handoff),
            "horizon_bdays": int(horizon),
            "max_overdue_days": int(escalation),
            "solver_time_limit_seconds": int(time_limit),
        })
        core.mark_schedule_dirty(auto_save=True)
        st.success("Advanced settings saved.")
        st.rerun()

    with st.expander("Current model interpretation", expanded=False):
        st.write(
            "The 55-day clock starts at the later of HRA approval and site selection. A trial becomes schedulable once Pharmacy has been notified. "
            "Recommended work cannot start before the selected planning date. By default, specialist workstreams use a 2-working-day handoff from the CT start date: "
            "after that handoff, Aseptic and ePMA may start in parallel and do not need to wait for CT completion. "
            "The CT capacity-accounting option is explicit above so staff can distinguish the conservative full-slot oversight assumption from CT-active-work-only accounting."
        )

core.render_page_navigation(
    previous_page="pages/06_Data_Assumptions.py",
    next_page="pages/02_Trial_Prioritisation.py",
    previous_label="Trials",
    next_label="Prioritise",
)
