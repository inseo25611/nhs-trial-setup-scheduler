from __future__ import annotations

from datetime import datetime
import inspect

import pandas as pd

import nhs_core as core
from scheduler_engine import solve_schedule_dissertation

DEFAULT_TIME_LIMIT_SECONDS = 60
REPRODUCIBLE_SEARCH_WORKERS = 1


def prepare_solver_input(trial_table, assumptions):
    """Build the solver input from the live, real-date operational view."""
    operational = core.build_operational_view(trial_table, assumptions)
    if operational.empty:
        return pd.DataFrame(), operational

    # Defence in depth for the conservative CT rule. The tracker has a CT start
    # milestone but no dedicated CT-completion milestone, so elapsed time must
    # never be subtracted from CT workload. Every non-completed trial retains
    # the full selected CT duration used for planning.
    completed_mask = operational.get(
        "effective_trial_status", pd.Series("", index=operational.index)
    ).astype(str).eq(core.STATUS_COMPLETED)
    full_ct = pd.to_numeric(
        operational.get("ct_duration_bdays", pd.Series(0, index=operational.index)),
        errors="coerce",
    ).fillna(0).clip(lower=0).round().astype(int)
    operational["ct_remaining_bdays"] = full_ct.where(~completed_mask, 0)

    setup_seen = pd.to_datetime(
        operational.get("observed_pharmacy_setup_start", operational.get("pharmacy_setup_start_date")),
        errors="coerce",
    ).notna()
    operational["ct_progress_status"] = "Not started"
    operational.loc[setup_seen & ~completed_mask, "ct_progress_status"] = "Started / completion not recorded"
    operational.loc[completed_mask, "ct_progress_status"] = "Completed"

    ready = operational.loc[
        operational.get("model_ready", pd.Series(False, index=operational.index)).fillna(False).astype(bool)
    ].copy()
    if ready.empty:
        return pd.DataFrame(), operational

    ready["release_date"] = pd.to_datetime(ready["operational_release_date"], errors="coerce")
    ready["due_date"] = pd.to_datetime(ready["due_date"], errors="coerce")
    # Optimise future planning demand at the planning date. Specialist completion
    # milestones remove completed branches completely. CT is conservative: because
    # there is no CT-completion milestone, a started but unfinished trial retains
    # the full selected CT planning allowance rather than subtracting elapsed time.
    ready["needs_aseptic"] = (
        ready["aseptic_required"].eq("Yes")
        & pd.to_numeric(ready.get("aseptic_remaining_bdays"), errors="coerce").fillna(0).gt(0)
    )
    ready["needs_epma"] = (
        ready["epma_required"].eq("Yes")
        & pd.to_numeric(ready.get("epma_remaining_bdays"), errors="coerce").fillna(0).gt(0)
    )
    ready["p_ct_total"] = pd.to_numeric(ready["ct_remaining_bdays"], errors="coerce").fillna(0)
    ready["p_aseptic"] = pd.to_numeric(ready["aseptic_remaining_bdays"], errors="coerce").fillna(0)
    ready["p_epma"] = pd.to_numeric(ready["epma_remaining_bdays"], errors="coerce").fillna(0)

    # Missing priorities use the positive-score cohort mean. If there are no
    # scores at all, all trials receive the same fallback weight, which is
    # mathematically equivalent to an equal-priority secondary objective.
    all_priority = pd.to_numeric(
        trial_table.get("priority_score", pd.Series(dtype=float)), errors="coerce"
    )
    observed = all_priority[all_priority > 0]
    priority_mean = float(observed.mean()) if len(observed) else float(core.DEFAULT_PRIORITY_FALLBACK)
    equal_priority_fallback = len(observed) == 0

    ready["priority_score"] = pd.to_numeric(ready["priority_score"], errors="coerce")
    ready["priority_is_mean_imputed"] = ready["priority_score"].isna() | (ready["priority_score"] <= 0)
    ready["priority_score"] = ready["priority_score"].where(ready["priority_score"] > 0, priority_mean)
    ready["priority_fallback_is_equal"] = equal_priority_fallback

    ready["manual_rank"] = pd.to_numeric(ready.get("manual_rank"), errors="coerce")
    ready["is_in_progress"] = ready["effective_trial_status"].eq(core.STATUS_IN_PROGRESS)

    bad_release = ready["release_date"].isna()
    bad_due = ready["due_date"].isna()
    bad_ct = ready["p_ct_total"].isna() | (ready["p_ct_total"] < 0)
    if bad_release.any():
        raise ValueError("Missing scheduling-ready date for: " + ", ".join(ready.loc[bad_release, "trial_id"].astype(str)))
    if bad_due.any():
        raise ValueError("Missing due date for: " + ", ".join(ready.loc[bad_due, "trial_id"].astype(str)))
    if bad_ct.any():
        raise ValueError("Invalid remaining CT duration for: " + ", ".join(ready.loc[bad_ct, "trial_id"].astype(str)))

    for col in ["p_ct_total", "p_aseptic", "p_epma"]:
        ready[col] = ready[col].round().astype(int)
    ready.loc[~ready["needs_aseptic"], "p_aseptic"] = 0
    ready.loc[~ready["needs_epma"], "p_epma"] = 0

    solver_columns = [
        "trial_id", "release_date", "due_date", "priority_score",
        "priority_is_mean_imputed", "priority_fallback_is_equal", "needs_aseptic", "needs_epma",
        "p_ct_total", "p_aseptic", "p_epma", "manual_rank", "is_in_progress",
    ]
    return ready[solver_columns].copy().reset_index(drop=True), operational


def solve_nhs_schedule(trial_table, assumptions, time_limit_seconds=None):
    # Validate imported/app-entered overrides even if the user has not visited
    # the Priorities page before generating the schedule.
    core.validate_manual_ranks(trial_table, assumptions)
    solver_df, operational = prepare_solver_input(trial_table, assumptions)
    if solver_df.empty:
        return {
            "schedule": pd.DataFrame(),
            "operational_view": operational,
            "summary": {"n_scheduled": 0, "n_on_time": 0, "n_late": 0, "average_margin_days": None},
            "technical_info": {"message": "No model-ready trials were available."},
        }

    planning_date = assumptions["planning_date"]
    if time_limit_seconds is None:
        time_limit_seconds = float(assumptions.get("solver_time_limit_seconds", DEFAULT_TIME_LIMIT_SECONDS))

    solver_kwargs = dict(
        waiting_df=solver_df,
        today=planning_date,
        specialist_handoff_bdays=int(assumptions.get("specialist_handoff_bdays", 0)),
        cap_ct=int(assumptions.get("cap_ct", 3)),
        cap_aseptic=int(assumptions.get("cap_aseptic", 2)),
        cap_epma=int(assumptions.get("cap_epma", 1)),
        horizon_bdays=int(assumptions.get("horizon_bdays", 250)),
        time_limit_s=float(time_limit_seconds),
        target_days=int(assumptions.get("target_days", 55)),
        ct_capacity_mode=str(assumptions.get("ct_capacity_mode", "continuous")),
        random_seed=42,
        num_search_workers=REPRODUCIBLE_SEARCH_WORKERS,
        diagnose_step1_ambiguity=False,
        capacity_exceptions=assumptions.get("capacity_exceptions", []),
        enforce_in_progress_precedence=False,
    )

    # Deployment-safe reproducible mode. The matching engine in this release
    # supports canonicalise_step2. If Streamlit is temporarily importing an
    # older/cached engine, do not crash: the operational run still uses a fixed
    # seed and one search worker. Canonicalisation switches on automatically as
    # soon as the matching engine is loaded.
    engine_params = inspect.signature(solve_schedule_dissertation).parameters
    canonicalisation_supported = "canonicalise_step2" in engine_params
    if canonicalisation_supported:
        solver_kwargs["canonicalise_step2"] = True

    raw_result = solve_schedule_dissertation(**solver_kwargs)

    schedule = raw_result.get("step2_result")
    if schedule is None:
        schedule = raw_result.get("step1_result")
    if schedule is None:
        raise RuntimeError("The scheduling engine could not generate a usable recommendation.")

    schedule = schedule.copy().reset_index(drop=True)

    metadata_cols = [
        "trial_id", "trial_status", "effective_trial_status", "hra_date", "site_date",
        "pharmacy_notified_date", "clock_start", "scheduling_ready_date", "operational_release_date",
        "pharmacy_setup_start_date", "aseptic_notify_date", "aseptic_bmr_authorised_date",
        "iqemo_setup_date", "iqemo_authorised_date", "greenlight_date",
        "observed_pharmacy_setup_start", "observed_aseptic_notify", "observed_aseptic_bmr_authorised",
        "observed_iqemo_setup", "observed_iqemo_authorised", "observed_greenlight",
        "aseptic_required", "epma_required", "prescribing_system", "ct_complexity", "epma_complexity",
        "ct_duration_bdays", "aseptic_duration_bdays", "epma_duration_bdays",
        "ct_remaining_bdays", "aseptic_remaining_bdays", "epma_remaining_bdays",
        "ct_progress_status", "aseptic_progress_status", "epma_progress_status",
        "queue_type", "scheduling_action", "trial_phase",
        "priority_source", "priority_is_mean_imputed", "manual_rank", "final_decision", "pharmacy_note",
        "overdue_days", "escalation_needed",
    ]
    metadata_cols = [c for c in metadata_cols if c in operational.columns]
    schedule = schedule.merge(operational[metadata_cols].copy(), on="trial_id", how="left", suffixes=("", "_meta"))

    # Prefer metadata copies when a field appears in both solver output and metadata.
    for col in ["manual_rank", "priority_is_mean_imputed"]:
        meta = f"{col}_meta"
        if meta in schedule.columns:
            schedule[col] = schedule[meta]
            schedule = schedule.drop(columns=[meta])

    for col in [
        "clock_start", "pharmacy_notified_date", "scheduling_ready_date", "operational_release_date",
        "pharmacy_setup_start_date", "aseptic_notify_date", "aseptic_bmr_authorised_date",
        "iqemo_setup_date", "iqemo_authorised_date", "greenlight_date",
        "observed_pharmacy_setup_start", "observed_aseptic_notify", "observed_aseptic_bmr_authorised",
        "observed_iqemo_setup", "observed_iqemo_authorised", "observed_greenlight",
        "CT_start_rec", "CT_end_rec", "CT_capacity_end_rec", "Aseptic_start_rec", "Aseptic_end_rec",
        "ePMA_start_rec", "ePMA_end_rec", "completion_rec", "due_date_rec",
    ]:
        if col in schedule.columns:
            schedule[col] = pd.to_datetime(schedule[col], errors="coerce")

    # Defensive display guard: a zero-duration branch occupies no workday and
    # must not be rendered as an end date earlier than its start date.
    zero_duration_specs = [
        ("ct_remaining_bdays", "CT_start_rec", "CT_end_rec"),
        ("aseptic_remaining_bdays", "Aseptic_start_rec", "Aseptic_end_rec"),
        ("epma_remaining_bdays", "ePMA_start_rec", "ePMA_end_rec"),
    ]
    for duration_col, start_col, end_col in zero_duration_specs:
        if duration_col in schedule.columns:
            zero = pd.to_numeric(schedule[duration_col], errors="coerce").fillna(0).le(0)
            if start_col in schedule.columns:
                schedule.loc[zero, start_col] = pd.NaT
            if end_col in schedule.columns:
                schedule.loc[zero, end_col] = pd.NaT

    schedule["margin_days"] = pd.to_numeric(schedule.get("margin_days"), errors="coerce")
    schedule["inherited_overdue_days"] = pd.to_numeric(schedule.get("overdue_days"), errors="coerce").fillna(0).astype(int)
    schedule["additional_tardiness_after_snapshot"] = (
        pd.to_numeric(schedule.get("tardiness_days_rec"), errors="coerce").fillna(0)
        - schedule["inherited_overdue_days"]
    ).clip(lower=0).astype(int)

    def margin_status(value):
        if pd.isna(value):
            return "Unknown"
        value = int(value)
        if value < 0:
            return "Predicted late"
        if value <= 14:
            return "Attention"
        return "Within target"

    schedule["schedule_status"] = schedule["margin_days"].apply(margin_status)

    # Recommended order comes from the actual recalculated solver solution.
    schedule = schedule.sort_values(
        ["CT_start_rec", "manual_rank", "priority_score", "trial_id"],
        ascending=[True, True, False, True],
        na_position="last",
    ).reset_index(drop=True)
    schedule["final_rank"] = range(1, len(schedule) + 1)

    n = len(schedule)
    n_on = int((schedule["margin_days"] >= 0).sum())
    n_late = int((schedule["margin_days"] < 0).sum())
    summary = {
        "n_scheduled": n,
        "n_on_time": n_on,
        "n_late": n_late,
        "on_time_pct": 100.0 * n_on / n if n else None,
        "average_margin_days": float(schedule["margin_days"].mean()) if n else None,
    }

    info = raw_result.get("info", {}) or {}
    technical = {
        "status_step1": info.get("status1"),
        "status_step2": info.get("status2"),
        "step1_on_time": info.get("u_star"),
        "step2_gap_pct": info.get("step2_optimality_gap_pct"),
        "runtime_step1_s": info.get("runtime_step1_s"),
        "runtime_step2_s": info.get("runtime_step2_s"),
        "horizon_used": info.get("horizon_used"),
        "horizon_was_extended": info.get("horizon_extended"),
        "capacity_exceptions": assumptions.get("capacity_exceptions", []),
        "existing_and_new_optimised_together": True,
        "reproducible_mode": True,
        "search_workers": REPRODUCIBLE_SEARCH_WORKERS,
        "random_seed": 42,
        "canonicalisation_supported_by_loaded_engine": bool(canonicalisation_supported),
        "canonicalisation_status": info.get("canonicalisation_status"),
        "canonicalisation_runtime_s": info.get("canonicalisation_runtime_s"),
        "calculated_at": datetime.now().isoformat(timespec="seconds"),
    }

    return {
        "schedule": schedule,
        "operational_view": operational,
        "summary": summary,
        "technical_info": technical,
    }
