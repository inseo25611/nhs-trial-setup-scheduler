"""CP-SAT scheduling engine used by the Pharmacy planning dashboard.

Workstreams: CT Pharmacy, Aseptic Services and electronic prescribing/ePMA.
The two-stage lexicographic objective is retained from the dissertation model,
while operational options such as manual precedence and temporary capacity
reductions are applied without assuming a fixed portfolio size or workbook layout.
"""

import time
from datetime import date

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

MODULE_VERSION = "2026-08-27-v22-reproducible-operational-canonicalisation"


def date_to_bday_index(base_date, target_date):
    """Convert an activity start date to a business-day start index."""
    base = np.datetime64(base_date, "D")
    target = np.datetime64(target_date, "D")
    return int(np.busday_count(base, target))


def calendar_due_to_latest_bday_index(base_date, due_date):
    """Return the inclusive end boundary of the latest on-time business day.

    Processing intervals use the half-open convention [start, end). Therefore a
    five-working-day task starting on Monday occupies business-day slots 0 to 4
    and has end boundary 5. A Friday due date must consequently map to boundary 5
    for that task to be classified as on time. Weekend due dates are rolled back
    to the preceding business day before the boundary is calculated.
    """
    base = np.datetime64(base_date, "D")
    due = np.datetime64(due_date, "D")
    latest_workday = np.busday_offset(due, 0, roll="backward")
    return int(np.busday_count(base, latest_workday)) + 1


def bday_index_to_date(base_date, n):
    """Convert a business-day start index to its calendar workday."""
    base = np.datetime64(base_date, "D")
    result = np.busday_offset(base, int(n), roll="forward")
    return pd.Timestamp(result).date()


def bday_end_index_to_date(base_date, n):
    """Convert a business-day end boundary to the final occupied workday."""
    base = np.datetime64(base_date, "D")
    result = np.busday_offset(base, int(n) - 1, roll="forward")
    return pd.Timestamp(result).date()


def urgency_score(days_remaining_calendar, target_days=55):
    """Retained for backwards compatibility; urgency is represented by due dates."""
    return max(0.0, (target_days - days_remaining_calendar) / target_days)


def build_priority_weight(priority_score, days_remaining_calendar=None, target_days=55):
    """Final Step-2 weight: organisational priority only; no urgency multiplier."""
    return float(priority_score)


def _extract_schedule(
    solver,
    today,
    ids,
    ct_s,
    ct_own_e,
    ct_capacity_e,
    a_s,
    a_e,
    e_s,
    e_e,
    completion,
    due_dates_calendar,
    on_time,
    tardiness,
    needs_aseptic,
    needs_epma,
    priority_score,
    priority_weight,
):
    def to_start_date(v):
        return bday_index_to_date(today, solver.Value(v))

    def to_end_date(v):
        return bday_end_index_to_date(today, solver.Value(v))

    def interval_dates(start_var, end_var):
        """Return visible dates for a positive-duration interval only.

        CP-SAT represents activities as half-open intervals [start, end).  A
        zero-duration interval therefore has end == start and occupies no date.
        Returning a display end date via `end - 1 business day` in that case
        would incorrectly make the end appear BEFORE the start.
        """
        if start_var is None or end_var is None:
            return None, None
        s_idx = int(solver.Value(start_var))
        e_idx = int(solver.Value(end_var))
        if e_idx <= s_idx:
            return None, None
        return (
            bday_index_to_date(today, s_idx),
            bday_end_index_to_date(today, e_idx),
        )

    ct_pairs = [interval_dates(sv, ev) for sv, ev in zip(ct_s, ct_own_e)]
    aseptic_pairs = [interval_dates(sv, ev) for sv, ev in zip(a_s, a_e)]
    epma_pairs = [interval_dates(sv, ev) for sv, ev in zip(e_s, e_e)]

    completion_dates = [to_end_date(v) for v in completion]
    rows = {
        "trial_id": ids,
        "needs_aseptic": needs_aseptic,
        "needs_epma": needs_epma,
        "priority_score": priority_score,
        "priority_weight": priority_weight,
        "CT_start_rec": [x[0] for x in ct_pairs],
        "CT_end_rec": [x[1] for x in ct_pairs],
        "CT_capacity_end_rec": [to_end_date(v) for v in ct_capacity_e],
        "Aseptic_start_rec": [x[0] for x in aseptic_pairs],
        "Aseptic_end_rec": [x[1] for x in aseptic_pairs],
        "ePMA_start_rec": [x[0] for x in epma_pairs],
        "ePMA_end_rec": [x[1] for x in epma_pairs],
        "completion_rec": completion_dates,
        "due_date_rec": due_dates_calendar,
        "on_time_rec": [bool(solver.Value(v)) for v in on_time],
        "tardiness_bdays_rec": [int(solver.Value(v)) for v in tardiness],
        "tardiness_days_rec": [max(0, (c - d).days) for c, d in zip(completion_dates, due_dates_calendar)],
        "margin_days": [(d - c).days for c, d in zip(completion_dates, due_dates_calendar)],
    }
    out = pd.DataFrame(rows)
    out = out.sort_values(
        ["CT_start_rec", "priority_weight", "trial_id"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    out.insert(0, "recommended_order", range(1, len(out) + 1))
    return out




def _add_solution_hint(model, solver, variables):
    """Seed a later solve with a complete incumbent from an earlier solve.

    Hints do not change the feasible region or objective; they only help CP-SAT
    reach a strong incumbent sooner. Duplicate variable references are ignored.
    """
    seen = set()
    for v in variables:
        if v is None:
            continue
        idx = v.Index()
        if idx in seen:
            continue
        seen.add(idx)
        model.AddHint(v, solver.Value(v))


def _configure_solver(solver, time_limit_s, num_search_workers, random_seed):
    """Common CP-SAT settings used for dissertation proof runs."""
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(num_search_workers)
    solver.parameters.random_seed = int(random_seed)
    # These settings preserve the mathematical model while strengthening proof search.
    solver.parameters.cp_model_presolve = True
    solver.parameters.symmetry_level = 2
    solver.parameters.linearization_level = 2

def solve_schedule_dissertation(
    waiting_df,
    today,
    specialist_handoff_bdays=0,
    cap_ct=3,
    cap_aseptic=2,
    cap_epma=1,
    horizon_bdays=250,
    horizon_buffer_bdays=30,
    time_limit_s=30,
    target_days=55,
    ct_capacity_mode="continuous",
    random_seed=42,
    num_search_workers=8,
    diagnose_step1_ambiguity=False,
    capacity_exceptions=None,
    enforce_in_progress_precedence=True,
    canonicalise_step2=False,
):
    """
    Solve the two-step lexicographic scheduling model.

    Optional scenario columns:
      release_date   -- scheduling availability date. If absent, clock_start is used.
      model_due_date -- due date used by the optimiser. If absent, due_date is used.

    Keeping these separate lets evaluation scenarios override release/due dates
    without overwriting the operational HRA/site/due-date fields.
    """
    if today is None:
        raise ValueError("An explicit evaluation/scenario reference date is required.")
    today = pd.Timestamp(today).date()

    if canonicalise_step2 and diagnose_step1_ambiguity:
        raise ValueError("canonicalise_step2 and diagnose_step1_ambiguity cannot be enabled together in the same solve.")

    df = waiting_df.reset_index(drop=True).copy()
    n = len(df)
    info_base = {
        "n_trials": n,
        "evaluation_date": today.isoformat(),
        "ct_capacity_mode": ct_capacity_mode,
        "cap_ct": cap_ct,
        "cap_aseptic": cap_aseptic,
        "cap_epma": cap_epma,
        "specialist_handoff_bdays": specialist_handoff_bdays,
        "target_days": target_days,
        "enforce_in_progress_precedence": bool(enforce_in_progress_precedence),
        "canonicalise_step2": bool(canonicalise_step2),
        "calendar_due_policy": (
            "calendar due dates are inclusive through the final eligible business day; "
            "weekend due dates roll back to the previous business day"
        ),
        "random_seed": random_seed,
        "num_search_workers": num_search_workers,
        "proof_strengthening": "tight implied domains + impossible-on-time fixing + Step-1 warm-start hint",
        "capacity_exceptions": capacity_exceptions or [],
    }
    if n == 0:
        return {
            "step1_result": None,
            "step2_result": None,
            "step1_worse_witness": None,
            "info": {**info_base, "u_star": 0, "status1": "no trials", "status2": "no trials", "status_witness": "not attempted"},
        }

    release_col = "release_date" if "release_date" in df.columns else "clock_start"
    due_col = "model_due_date" if "model_due_date" in df.columns else "due_date"
    release_dates = pd.to_datetime(df[release_col], errors="coerce").dt.date.tolist()
    due_dates_calendar = pd.to_datetime(df[due_col], errors="coerce").dt.date.tolist()
    if any(pd.isna(x) for x in release_dates) or any(pd.isna(x) for x in due_dates_calendar):
        raise ValueError("Every scheduled trial must have a valid release date and model due date.")

    release_bday = [date_to_bday_index(today, d) for d in release_dates]
    due_bday_raw = [calendar_due_to_latest_bday_index(today, d) for d in due_dates_calendar]
    days_remaining_calendar = [(d - today).days for d in due_dates_calendar]

    max_due_needed = max([0] + [d for d in due_bday_raw if d > 0])
    max_release = max([0] + release_bday)

    # Guaranteed-feasible horizon upper bound: imagine processing the trials one at
    # a time. For each trial, its total elapsed span is the longest required branch.
    # Summing those spans is conservative but prevents a large cohort from becoming
    # falsely INFEASIBLE merely because the requested horizon was too short.
    serial_spans = []
    for _, row in df.iterrows():
        span = int(row["p_ct_total"])
        if bool(row["needs_aseptic"]):
            span = max(span, int(specialist_handoff_bdays) + int(row["p_aseptic"]))
        if bool(row["needs_epma"]):
            span = max(span, int(specialist_handoff_bdays) + int(row["p_epma"]))
        serial_spans.append(span)
    serial_upper_bound = max_release + sum(serial_spans) + int(horizon_buffer_bdays)

    # Staff absence / temporary reduced-capacity windows can extend a feasible
    # schedule. Add a conservative business-day allowance so the model is not
    # declared infeasible merely because a long absence falls inside the horizon.
    absence_extension = 0
    for ex in capacity_exceptions or []:
        try:
            start = pd.Timestamp(ex.get("start_date")).date()
            end = pd.Timestamp(ex.get("end_date")).date()
            if end >= start:
                first = np.busday_offset(np.datetime64(start, "D"), 0, roll="forward")
                last = np.busday_offset(np.datetime64(end, "D"), 0, roll="backward")
                if last >= first:
                    absence_extension += int(np.busday_count(first, last)) + 1
        except Exception:
            continue

    required_horizon = max(
        max_due_needed + int(horizon_buffer_bdays),
        serial_upper_bound + int(absence_extension),
    )
    horizon = max(int(horizon_bdays), int(required_horizon))
    most_overdue = min([0] + due_bday_raw)
    tardiness_upper_bound = horizon + max(0, -most_overdue) + horizon_buffer_bdays

    priority_score = df["priority_score"].astype(float).tolist()
    for i, p in enumerate(priority_score):
        if not (p > 0):
            raise ValueError(f"priority_score must be positive for {df.loc[i, 'trial_id']}: {p}")
    weights = [build_priority_weight(p, r, target_days) for p, r in zip(priority_score, days_remaining_calendar)]

    model = cp_model.CpModel()
    ids = df["trial_id"].astype(str).tolist()
    needs_aseptic = df["needs_aseptic"].astype(bool).tolist()
    needs_epma = df["needs_epma"].astype(bool).tolist()

    ct_s, ct_own_e, ct_capacity_e, ct_iv, ct_demands = [], [], [], [], []
    a_s, a_e, a_iv, a_demands = [], [], [], []
    e_s, e_e, e_iv, e_demands = [], [], [], []
    completion, on_time, tardiness = [], [], []

    for i, row in df.iterrows():
        p_ct = int(row["p_ct_total"])
        p_a = int(row["p_aseptic"])
        p_e = int(row["p_epma"])
        release = max(0, int(release_bday[i]))

        # Tight per-trial domains. These bounds are implied by the original model,
        # so they improve propagation without changing any feasible schedule.
        min_span = p_ct
        if needs_aseptic[i]:
            min_span = max(min_span, int(specialist_handoff_bdays) + p_a)
        if needs_epma[i]:
            min_span = max(min_span, int(specialist_handoff_bdays) + p_e)
        earliest_completion = release + min_span
        latest_start = horizon - min_span

        s = model.NewIntVar(release, latest_start, f"ct_s_{i}")
        own_e = model.NewIntVar(release + p_ct, horizon, f"ct_own_e_{i}")
        model.Add(own_e == s + p_ct)
        stage_ends = [own_e]

        if needs_aseptic[i]:
            sa_lb = release + int(specialist_handoff_bdays)
            sa = model.NewIntVar(sa_lb, horizon - p_a, f"a_s_{i}")
            ea = model.NewIntVar(sa_lb + p_a, horizon, f"a_e_{i}")
            iva = model.NewIntervalVar(sa, p_a, ea, f"a_iv_{i}")
            model.Add(sa >= s + specialist_handoff_bdays)
            a_s.append(sa); a_e.append(ea); a_iv.append(iva); a_demands.append(1)
            stage_ends.append(ea)
        else:
            a_s.append(None); a_e.append(None)

        if needs_epma[i]:
            epma_lb = release + int(specialist_handoff_bdays)
            se = model.NewIntVar(epma_lb, horizon - p_e, f"epma_s_{i}")
            ee = model.NewIntVar(epma_lb + p_e, horizon, f"epma_e_{i}")
            ive = model.NewIntervalVar(se, p_e, ee, f"epma_iv_{i}")
            model.Add(se >= s + specialist_handoff_bdays)
            e_s.append(se); e_e.append(ee); e_iv.append(ive); e_demands.append(1)
            stage_ends.append(ee)
        else:
            e_s.append(None); e_e.append(None)

        c = model.NewIntVar(earliest_completion, horizon, f"completion_{i}")
        model.AddMaxEquality(c, stage_ends)
        completion.append(c)

        if ct_capacity_mode == "ct_own_duration_only":
            cap_e = own_e
            ct_interval = model.NewIntervalVar(s, p_ct, own_e, f"ct_iv_{i}")
        elif ct_capacity_mode == "continuous":
            cap_e = c
            ct_size = model.NewIntVar(0, horizon, f"ct_size_{i}")
            model.Add(ct_size == c - s)
            ct_interval = model.NewIntervalVar(s, ct_size, c, f"ct_iv_{i}")
        else:
            raise ValueError("ct_capacity_mode must be 'continuous' or 'ct_own_duration_only'.")

        ct_s.append(s); ct_own_e.append(own_e); ct_capacity_e.append(cap_e); ct_iv.append(ct_interval); ct_demands.append(1)

        d = int(due_bday_raw[i])
        ot = model.NewBoolVar(f"on_time_{i}")
        if d < earliest_completion:
            # Even the earliest possible completion misses the deadline.
            model.Add(ot == 0)
        elif d >= horizon:
            model.Add(ot == 1)
        else:
            model.Add(c <= d).OnlyEnforceIf(ot)
            model.Add(c > d).OnlyEnforceIf(ot.Not())
        on_time.append(ot)

        tard_ub_i = max(0, horizon - d)
        tard = model.NewIntVar(0, tard_ub_i, f"tardiness_{i}")
        if d < earliest_completion:
            # c - d is strictly positive over the entire domain.
            model.Add(tard == c - d)
        elif d >= horizon:
            model.Add(tard == 0)
        else:
            model.AddMaxEquality(tard, [0, c - d])
        tardiness.append(tard)

    # --------------------------------------------------------
    # Operational continuity + manual override constraints
    # --------------------------------------------------------
    # The automatic rule keeps unranked in-progress work ahead of unranked
    # not-started work. A saved manual queue order is an explicit Pharmacy
    # override and therefore takes precedence over that automatic continuity
    # preference. Rank is still a start-precedence relation rather than a
    # one-at-a-time sequence, so capacity >1 can give equal CT start dates.
    in_progress = (
        df.get("is_in_progress", pd.Series([False] * n)).fillna(False).astype(bool).tolist()
    )
    manual_rank = pd.to_numeric(
        df.get("manual_rank", pd.Series([None] * n)), errors="coerce"
    ).tolist()
    ranked = [i for i, r in enumerate(manual_rank) if pd.notna(r) and float(r) > 0]
    ranked_set = set(ranked)

    # Explicit manual ranks override the automatic continuity preference.
    for i in ranked:
        for j in ranked:
            if i != j and float(manual_rank[i]) < float(manual_rank[j]):
                model.Add(ct_s[i] <= ct_s[j])
        for j in range(n):
            if j != i and j not in ranked_set:
                model.Add(ct_s[i] <= ct_s[j])

    # Optional operational-continuity rule.  The dissertation engine keeps this
    # available for backward compatibility, but the NHS rolling-horizon app
    # disables it so that existing residual work and newly arrived work compete
    # in the same lexicographic optimisation.  This lets Step 1 genuinely
    # maximise the number completed on time; explicit manual ranks still act as
    # hard Pharmacy overrides when staff need to protect a particular sequence.
    if enforce_in_progress_precedence:
        for i in range(n):
            if i in ranked_set or not in_progress[i]:
                continue
            for j in range(n):
                if j != i and j not in ranked_set and not in_progress[j]:
                    model.Add(ct_s[i] <= ct_s[j])

    # --------------------------------------------------------
    # Temporary resource reductions (staff absence, training, etc.)
    # --------------------------------------------------------
    def add_capacity_blocks(team, base_capacity, intervals, demands):
        if base_capacity <= 0:
            return
        daily_capacity = [int(base_capacity)] * int(horizon)
        for ex in capacity_exceptions or []:
            if str(ex.get("workstream", "")).strip() != team:
                continue
            try:
                available = int(ex.get("available_capacity"))
                available = max(0, min(int(base_capacity), available))
                start_date = pd.Timestamp(ex.get("start_date")).date()
                end_date = pd.Timestamp(ex.get("end_date")).date()
                if end_date < start_date:
                    continue
                first = np.busday_offset(np.datetime64(start_date, "D"), 0, roll="forward")
                last = np.busday_offset(np.datetime64(end_date, "D"), 0, roll="backward")
                if last < first:
                    continue
                start_idx = max(0, int(np.busday_count(np.datetime64(today, "D"), first)))
                end_idx = min(
                    int(horizon),
                    int(np.busday_count(np.datetime64(today, "D"), last)) + 1,
                )
                for t in range(start_idx, max(start_idx, end_idx)):
                    daily_capacity[t] = min(daily_capacity[t], available)
            except Exception:
                continue

        # Compress consecutive days with the same reduced capacity into one
        # fixed blocking interval. Its demand consumes the unavailable slots.
        t = 0
        block_no = 0
        while t < int(horizon):
            cap = daily_capacity[t]
            if cap >= int(base_capacity):
                t += 1
                continue
            start = t
            while t < int(horizon) and daily_capacity[t] == cap:
                t += 1
            size = t - start
            reduction = int(base_capacity) - int(cap)
            if size > 0 and reduction > 0:
                # Use the long-standing IntervalVar API for broad OR-Tools compatibility.
                iv = model.NewIntervalVar(start, size, start + size, f"{team}_capacity_block_{block_no}")
                intervals.append(iv)
                demands.append(reduction)
                block_no += 1

    add_capacity_blocks("CT", int(cap_ct), ct_iv, ct_demands)
    add_capacity_blocks("Aseptic", int(cap_aseptic), a_iv, a_demands)
    add_capacity_blocks("ePMA", int(cap_epma), e_iv, e_demands)

    model.AddCumulative(ct_iv, ct_demands, int(cap_ct))
    if a_iv:
        model.AddCumulative(a_iv, a_demands, int(cap_aseptic))
    if e_iv:
        model.AddCumulative(e_iv, e_demands, int(cap_epma))

    # Step 1: maximise number of on-time trials.
    model.Maximize(sum(on_time))
    solver1 = cp_model.CpSolver()
    _configure_solver(solver1, time_limit_s, num_search_workers, random_seed)
    t0 = time.perf_counter()
    status1 = solver1.Solve(model)
    runtime1 = time.perf_counter() - t0

    if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "step1_result": None,
            "step2_result": None,
            "step1_worse_witness": None,
            "info": {
                **info_base,
                "status1": solver1.StatusName(status1),
                "status2": "not attempted",
                "horizon_used": horizon,
                "horizon_extended": horizon > horizon_bdays,
            },
        }

    u_star = int(round(solver1.ObjectiveValue()))
    step1_result = _extract_schedule(
        solver1, today, ids, ct_s, ct_own_e, ct_capacity_e, a_s, a_e, e_s, e_e,
        completion, due_dates_calendar, on_time, tardiness,
        needs_aseptic, needs_epma, priority_score, weights,
    )

    # Step 2: retain Step-1 optimum and minimise priority-weighted tardiness.
    model.Add(sum(on_time) == u_star)
    scaled_weights = [int(round(w * 100)) for w in weights]
    weighted_tardiness_expr = sum(scaled_weights[i] * tardiness[i] for i in range(n))
    model.Minimize(weighted_tardiness_expr)

    # Warm-start Step 2 from the proven Step-1 optimum. This does not constrain
    # Step 2; it simply supplies CP-SAT with a strong feasible incumbent.
    hint_vars = ct_s + ct_own_e + ct_capacity_e + a_s + a_e + e_s + e_e + completion + on_time + tardiness
    _add_solution_hint(model, solver1, hint_vars)

    solver2 = cp_model.CpSolver()
    _configure_solver(solver2, time_limit_s, num_search_workers, random_seed)
    t0 = time.perf_counter()
    status2 = solver2.Solve(model)
    runtime2 = time.perf_counter() - t0

    if status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "step1_result": step1_result,
            "step2_result": None,
            "step1_worse_witness": None,
            "info": {
                **info_base,
                "u_star": u_star,
                "status1": solver1.StatusName(status1),
                "status2": solver2.StatusName(status2),
                "objective_step1": u_star,
                "runtime_step1_s": runtime1,
                "horizon_used": horizon,
                "horizon_extended": horizon > horizon_bdays,
            },
        }

    step2_result = _extract_schedule(
        solver2, today, ids, ct_s, ct_own_e, ct_capacity_e, a_s, a_e, e_s, e_e,
        completion, due_dates_calendar, on_time, tardiness,
        needs_aseptic, needs_epma, priority_score, weights,
    )
    objective_unscaled = float(
        sum(w * t for w, t in zip(weights, step2_result.sort_values("trial_id").set_index("trial_id").loc[ids, "tardiness_bdays_rec"].tolist()))
    )
    objective_scaled = float(solver2.ObjectiveValue())
    best_bound_scaled = float(solver2.BestObjectiveBound())
    if abs(objective_scaled) < 1e-9:
        step2_gap_pct = 0.0 if abs(best_bound_scaled) < 1e-9 else None
    else:
        step2_gap_pct = max(0.0, (objective_scaled - best_bound_scaled) / abs(objective_scaled) * 100.0)

    # Optional diagnostic: test whether Step 1 leaves secondary schedule quality
    # under-determined. We deliberately avoid a horizon-maximising "bad" schedule.
    #
    # Stage W1: find the *nearest strictly worse* weighted-tardiness value that still
    # preserves the same Step-1 optimum u*.
    # Stage W2: fix that nearest-worse value and minimise total completion time. This
    # left-shifts the witness and removes gratuitous idling as far as the model can,
    # making the witness more defensible for dissertation interpretation.
    witness_result = None
    status_witness_name = "not attempted"
    status_witness_leftshift_name = "not attempted"
    witness_objective_scaled = None
    witness_objective_unscaled = None
    witness_delta_unscaled = None
    runtime_witness = None
    runtime_witness_leftshift = None
    if bool(diagnose_step1_ambiguity) and status2 == cp_model.OPTIMAL:
        best_scaled = int(round(solver2.ObjectiveValue()))
        model.Add(weighted_tardiness_expr >= best_scaled + 1)
        model.Minimize(weighted_tardiness_expr)

        solver3 = cp_model.CpSolver()
        _configure_solver(solver3, time_limit_s, num_search_workers, random_seed)
        t0 = time.perf_counter()
        status3 = solver3.Solve(model)
        runtime_witness = time.perf_counter() - t0
        status_witness_name = solver3.StatusName(status3)

        if status3 == cp_model.OPTIMAL:
            nearest_worse_scaled = int(round(solver3.ObjectiveValue()))
            model.Add(weighted_tardiness_expr == nearest_worse_scaled)
            model.Minimize(sum(completion))

            solver4 = cp_model.CpSolver()
            _configure_solver(solver4, time_limit_s, num_search_workers, random_seed)
            t0 = time.perf_counter()
            status4 = solver4.Solve(model)
            runtime_witness_leftshift = time.perf_counter() - t0
            status_witness_leftshift_name = solver4.StatusName(status4)

            if status4 == cp_model.OPTIMAL:
                witness_result = _extract_schedule(
                    solver4, today, ids, ct_s, ct_own_e, ct_capacity_e, a_s, a_e, e_s, e_e,
                    completion, due_dates_calendar, on_time, tardiness,
                    needs_aseptic, needs_epma, priority_score, weights,
                )
                witness_objective_scaled = float(nearest_worse_scaled)
                witness_tard = witness_result.set_index("trial_id").loc[ids, "tardiness_bdays_rec"].tolist()
                witness_objective_unscaled = float(sum(w * t for w, t in zip(weights, witness_tard)))
                witness_delta_unscaled = witness_objective_unscaled - objective_unscaled
            elif status4 == cp_model.FEASIBLE:
                status_witness_leftshift_name = "FEASIBLE (left-shift optimum not proved; not used as dissertation evidence)"
        elif status3 == cp_model.FEASIBLE:
            # A feasible but not proven-nearest witness is not used as dissertation
            # evidence. Keep the status so the UI can say the diagnostic is unresolved.
            status_witness_leftshift_name = "not attempted: nearest-worse optimum not proved"

    # --------------------------------------------------------
    # Optional deterministic canonicalisation for the operational app.
    # --------------------------------------------------------
    # Step 2 can legitimately stop at FEASIBLE under a time limit.  In that case
    # several schedules can have exactly the same incumbent Step-2 objective, and
    # a parallel search may return different trial-level dates from run to run.
    # When requested by the operational adapter, freeze the incumbent weighted-
    # tardiness value and select one canonical schedule from that objective level:
    #   1) minimise total completion time (remove gratuitous idling), then
    #   2) use a stable trial-ID-weighted CT-start expression to break residual ties.
    # This NEVER trades away the Step-1 optimum or worsens the Step-2 incumbent
    # objective; it only selects a repeatable representative among schedules with
    # the exact same weighted-tardiness value.
    canonical_status_name = "not requested"
    canonical_runtime_s = None
    canonical_result = None
    canonical_objective = None
    if bool(canonicalise_step2):
        incumbent_scaled = int(round(objective_scaled))
        model.Add(weighted_tardiness_expr == incumbent_scaled)

        # Canonical tie-break.  Total completion time dominates the secondary
        # stable-start term by construction, so the latter is used only when the
        # total completion sum is identical.
        alphabetical = sorted(range(n), key=lambda i: ids[i])
        stable_weight = {idx: n - pos for pos, idx in enumerate(alphabetical)}
        stable_start_expr = sum(int(stable_weight[i]) * ct_s[i] for i in range(n))
        max_stable_start = int(horizon) * sum(int(v) for v in stable_weight.values())
        completion_scale = max_stable_start + 1
        canonical_expr = completion_scale * sum(completion) + stable_start_expr
        model.Minimize(canonical_expr)

        solver_canonical = cp_model.CpSolver()
        _configure_solver(solver_canonical, time_limit_s, num_search_workers, random_seed)
        t0 = time.perf_counter()
        status_canonical = solver_canonical.Solve(model)
        canonical_runtime_s = time.perf_counter() - t0
        canonical_status_name = solver_canonical.StatusName(status_canonical)

        if status_canonical in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            canonical_result = _extract_schedule(
                solver_canonical, today, ids, ct_s, ct_own_e, ct_capacity_e, a_s, a_e, e_s, e_e,
                completion, due_dates_calendar, on_time, tardiness,
                needs_aseptic, needs_epma, priority_score, weights,
            )
            canonical_objective = float(solver_canonical.ObjectiveValue())
            # The equality above guarantees that the operationally reported Step-2
            # objective is unchanged.  Only the representative schedule is replaced.
            step2_result = canonical_result

    info = {
        **info_base,
        "u_star": u_star,
        "status1": solver1.StatusName(status1),
        "status2": solver2.StatusName(status2),
        "status_witness": status_witness_name,
        "status_witness_leftshift": status_witness_leftshift_name,
        "objective_step1": u_star,
        "objective_step2_scaled": objective_scaled,
        "objective_step2_best_bound_scaled": best_bound_scaled,
        "step2_optimality_gap_pct": step2_gap_pct,
        "objective_step2_unscaled": objective_unscaled,
        "witness_objective_scaled": witness_objective_scaled,
        "witness_objective_unscaled": witness_objective_unscaled,
        "witness_delta_unscaled": witness_delta_unscaled,
        "step1_secondary_ambiguity_proved": witness_result is not None,
        "runtime_step1_s": runtime1,
        "runtime_step2_s": runtime2,
        "canonicalisation_status": canonical_status_name,
        "canonicalisation_runtime_s": canonical_runtime_s,
        "canonicalisation_objective": canonical_objective,
        "runtime_witness_s": runtime_witness,
        "runtime_witness_leftshift_s": runtime_witness_leftshift,
        "horizon_used": horizon,
        "horizon_extended": horizon > horizon_bdays,
        "serial_feasible_upper_bound": serial_upper_bound,
    }
    return {
        "step1_result": step1_result,
        "step2_result": step2_result,
        "step1_worse_witness": witness_result,
        "info": info,
    }
