"""Synthetic sample portfolio for demonstrating the planning tool.

Every trial name, date, score and note below is fictitious. Dates are generated
relative to the planning date so the demo always shows a realistic, current
portfolio: most trials are active, a few are complete, and some have data gaps
for the Data quality checks to surface.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# name, HRA offset, site-selected offset, notified offset (None = not yet notified),
# set-up start offset, aseptic, prescribing system, CT complexity, ePMA complexity,
# priority, phase, green-light offset (None = still in progress), note
_TRIALS = [
    ("RINVIL-301",            -120,  -48,  -44,  -40, "Y", "chemo ePMA",     "Complex",  "Moderate", 35,   "3", None, ""),
    ("SORNOV-3",              -95,   -41,  -38,  -35, "Y", "chemo ePMA",     "Moderate", "Complex",  30,   "3", None, ""),
    ("TORDAX",                -80,   -36,  -33,  -30, "N", "none",           "Simple",   None,       None, "2", None, ""),
    ("ELQUINTA-03",           -70,   -30,  -27,  None,"Y", "inpatient ePMA", "Moderate", "Simple",   25,   "2", None, "Sponsor documents still awaited."),
    ("MIRNO",                 -64,   -29,  -24,  -20, "N", "chemo ePMA",     "Moderate", "Moderate", None, "3", None, ""),
    ("ARSTE",                 -60,   -26,  -22,  None,"N", "none",           "Simple",   None,       28.5, "2", None, ""),
    ("SELHE",                 -58,   -22,  -19,  -15, "Y", "none",           "Complex",  None,       35,   "3", None, ""),
    ("CORPEX (DGT-9102)",     -55,   -20,  -16,  None,"Y", "chemo ePMA",     None,       None,       None, "1 to 2", None, "Complexity not yet assessed."),
    ("DROMON (GLT-3008)",     -50,   -17,  -12,  -10, "Y", "chemo ePMA",     "Complex",  "Complex",  35,   "3", None, ""),
    ("LL-5917-169",           -45,   -14,  -9,   None,"N", "inpatient ePMA", "Simple",   "Simple",   None, "2", None, ""),
    ("TANBRIM",               -40,   -10,  -6,   None,"N", "none",           "Moderate", None,       25,   "3", None, ""),
    ("STERSTER",              -36,   -8,   -3,   None,"Y", "chemo ePMA",     "Moderate", "Moderate", None, "3", None, ""),
    ("AMX-7568-115",          -30,   -6,   None, None,"N", "chemo ePMA",     "Simple",   "Moderate", None, "2", None, "Awaiting pharmacy notification."),
    ("NOVDAXU (XWX-3564)",    -25,   -4,   None, None,"Y", "none",           "Moderate", None,       30,   "3", None, ""),
    ("PYRDROEL (HRX-1878)",   -20,   12,   None, None,"N", "chemo ePMA",     "Simple",   "Simple",   None, "2", None, "Site selection expected next month."),
    ("ORDRO",                 -260,  -230, -226, -220,"Y", "none",           "Complex",  None,       None, "3", -110, ""),
    ("GARTAN",                -210,  -190, -185, -180,"N", "chemo ePMA",     "Moderate", "Simple",   None, "2", -120, ""),
    ("VERQUI-01",             -200,  -170, -168, -160,"N", "none",           "Simple",   None,       None, "3", -125, ""),
    ("SELMELT",               -180,  -150, -146, -140,"Y", "chemo ePMA",     "Complex",  "Complex",  None, "3", -40,  ""),
    ("PEXMEL-02",             -150,  -120, -118, -110,"N", "inpatient ePMA", "Moderate", "Moderate", None, "2", -50,  ""),
]


def build_sample_dataframe(planning_date: date | None = None) -> pd.DataFrame:
    today = planning_date or date.today()
    d = lambda off: (today + timedelta(days=off)) if off is not None else None
    rows = []
    for i, (name, hra, site, notified, start, asep, presc, ct, epma, prio, phase, gl, note) in enumerate(_TRIALS, 1):
        notified_d = d(notified)
        # Specialist milestones for trials that are under way or complete.
        bmr = d(gl - 3) if (asep == "Y" and gl is not None) else None
        iq_set = d(start + 15) if (presc != "none" and start is not None and start + 15 <= 0) else None
        iq_auth = d(gl - 5) if (presc != "none" and gl is not None) else None
        rows.append({
            "#": i,
            "Trial": name,
            "Trial status": "Completed" if gl is not None else "",
            "HRA approval": d(hra),
            "Site selected": d(site),
            "Pharmacy notified": notified_d,
            "Pharmacy set-up start": d(start),
            "Aseptic": asep,
            "Aseptic BMR authorised": bmr,
            "Prescribing system": presc,
            "iQemo Template set up": iq_set,
            "iQemo template authorised": iq_auth,
            "Pharmacy green light": d(gl),
            "Trial Complexity": ct or "",
            "ePMA Complexity": epma or "",
            "Priority score": prio,
            "Trial phase": phase,
            "Notes": note,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "sample_data/sample_trials.xlsx"
    build_sample_dataframe().to_excel(out, index=False, sheet_name="Trials")
    print("wrote", out)
