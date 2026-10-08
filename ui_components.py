from __future__ import annotations

from html import escape
from typing import Iterable

import pandas as pd
import streamlit as st

# Unified semantic palette used throughout the operational UI.
PRIMARY = "#005EB8"          # NHS-style blue: active / scheduled / primary action
PRIMARY_DARK = "#003D78"
PRIMARY_SOFT = "#E8F1FA"
GREEN = "#16844A"            # complete / on time
GREEN_SOFT = "#E9F7EF"
AMBER = "#B86B00"            # attention / approaching due
AMBER_SOFT = "#FFF4DB"
RED = "#C62828"              # late / blocked
RED_SOFT = "#FDECEC"
GREY = "#667085"             # N/A / secondary
GREY_SOFT = "#F2F4F7"
INK = "#1D2939"
MUTED = "#667085"
BORDER = "#D0D5DD"
SURFACE = "#FFFFFF"


def apply_global_styles():
    """Apply a light, consistent operational-dashboard style to every page."""
    st.markdown(
        f"""
        <style>
        /* Keep Streamlit's own top padding. It is version-aware and leaves room
           for the fixed top navigation. A small custom padding pushes the first
           app element underneath the navigation bar. */
        .block-container {{
            padding-bottom: 2.5rem;
            max-width: 1500px;
        }}
        h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.015em; }}
        [data-testid="stCaptionContainer"] {{ color: {MUTED}; }}
        div[data-testid="stMetric"] {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 14px;
            padding: 0.8rem 1rem;
        }}
        div[data-testid="stMetricLabel"] {{ color: {MUTED}; }}
        div[data-testid="stMetricValue"] {{ color: {INK}; }}
        .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
            background: {PRIMARY};
            border-color: {PRIMARY};
        }}
        .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
            background: {PRIMARY_DARK};
            border-color: {PRIMARY_DARK};
        }}
        div[data-baseweb="tab-list"] {{ gap: 0.35rem; }}
        button[data-baseweb="tab"] {{
            border-radius: 10px 10px 0 0;
            padding-left: 1rem;
            padding-right: 1rem;
        }}
        /* Sticky must be applied to Streamlit's element wrapper. If only the
           inner markdown div is sticky, its own wrapper clips it underneath the
           fixed top navigation. */
        div[data-testid="stElementContainer"]:has(.planning-status-bar),
        div.element-container:has(.planning-status-bar) {{
            position: sticky !important;
            top: 4.75rem !important;
            z-index: 900 !important;
            background: transparent;
        }}
        .planning-status-bar {{
            position: relative !important;
            top: auto !important;
            z-index: auto;
            display: flex;
            gap: 0.55rem;
            align-items: center;
            flex-wrap: wrap;
            padding: 0.62rem 0.8rem;
            margin: 0.25rem 0 1rem 0;
            background: rgba(255,255,255,0.98);
            backdrop-filter: blur(8px);
            border: 1px solid {BORDER};
            border-left: 4px solid {PRIMARY};
            border-radius: 12px;
            box-shadow: 0 3px 12px rgba(16,24,40,0.06);
        }}
        @media (max-width: 900px) {{
            div[data-testid="stElementContainer"]:has(.planning-status-bar),
            div.element-container:has(.planning-status-bar) {{
                top: 5.25rem !important;
            }}
        }}
        .status-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.26rem 0.58rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 650;
            line-height: 1.2;
            white-space: nowrap;
        }}
        .mini-stat-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin: 0.55rem 0 1rem 0;
        }}
        .mini-stat {{
            border: 1px solid {BORDER};
            border-radius: 999px;
            background: {GREY_SOFT};
            color: {INK};
            padding: 0.32rem 0.72rem;
            font-size: 0.82rem;
        }}
        .queue-card {{
            border: 1px solid {BORDER};
            border-radius: 14px;
            padding: 0.85rem 0.95rem;
            min-height: 126px;
            background: {SURFACE};
            box-shadow: 0 2px 8px rgba(16,24,40,0.035);
        }}
        .queue-rank {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 2rem;
            height: 2rem;
            border-radius: 999px;
            background: {PRIMARY};
            color: white;
            font-weight: 750;
            margin-right: 0.45rem;
        }}
        .trial-card {{
            border: 1px solid {BORDER};
            border-radius: 16px;
            padding: 1rem 1.1rem;
            background: {SURFACE};
            box-shadow: 0 2px 10px rgba(16,24,40,0.04);
        }}
        .section-kicker {{
            color: {PRIMARY};
            font-size: 0.77rem;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0.055em;
            margin-bottom: 0.2rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def metric_card(host, label, value, *, tone="neutral", help_text: str | None = None):
    palette = {
        "primary": (PRIMARY_SOFT, "#B5D2EC", PRIMARY_DARK),
        "success": (GREEN_SOFT, "#B7E0C8", GREEN),
        "warning": (AMBER_SOFT, "#F2D291", AMBER),
        "danger": (RED_SOFT, "#F0B8B8", RED),
        "neutral": (GREY_SOFT, BORDER, INK),
    }
    bg, border, value_color = palette.get(tone, palette["neutral"])
    help_html = f'<div style="font-size:0.72rem;color:{MUTED};margin-top:6px;">{escape(help_text)}</div>' if help_text else ""
    host.markdown(
        f"""
        <div style="background:{bg};border:1px solid {border};border-radius:14px;padding:14px 16px 12px;min-height:106px;">
            <div style="font-size:0.84rem;color:{MUTED};margin-bottom:8px;">{escape(str(label))}</div>
            <div style="font-size:1.95rem;font-weight:760;line-height:1.05;color:{value_color};">{escape(str(value))}</div>
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _chip(text: str, *, fg: str, bg: str, dot: str | None = None) -> str:
    dot_html = f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};display:inline-block;"></span>' if dot else ""
    return f'<span class="status-chip" style="color:{fg};background:{bg};">{dot_html}{escape(str(text))}</span>'


def status_chip_html(value) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if "completed" in low or "authorised" in low or "on time" in low:
        return _chip(text or "Completed", fg=GREEN, bg=GREEN_SOFT, dot=GREEN)
    if "need" in low or "blocked" in low or "late" in low or "missing" in low:
        return _chip(text or "Needs attention", fg=RED, bg=RED_SOFT, dot=RED)
    if "await" in low or "overdue" in low or "attention" in low or "approach" in low:
        return _chip(text, fg=AMBER, bg=AMBER_SOFT, dot=AMBER)
    if low in {"n/a", "na", "—", "-", ""}:
        return _chip(text or "N/A", fg=GREY, bg=GREY_SOFT, dot=GREY)
    if "in progress" in low or "started" in low or "scheduled" in low or "ready" in low:
        return _chip(text, fg=PRIMARY_DARK, bg=PRIMARY_SOFT, dot=PRIMARY)
    if "not started" in low or "not yet" in low:
        return _chip(text, fg=GREY, bg=GREY_SOFT, dot=GREY)
    return _chip(text, fg=INK, bg=GREY_SOFT, dot=GREY)


def status_label(value) -> str:
    """Plain-text badge label that remains readable inside Streamlit dataframes."""
    text = str(value or "").strip()
    low = text.lower()
    if "completed" in low or "authorised" in low:
        return f"🟢 {text or 'Completed'}"
    if "need" in low or "blocked" in low or "late" in low or "missing" in low:
        return f"🔴 {text or 'Needs attention'}"
    if "await" in low or "overdue" in low or "attention" in low or "approach" in low:
        return f"🟠 {text}"
    if low in {"n/a", "na", "—", "-", ""}:
        return "⚪ N/A" if low in {"n/a", "na"} else text
    if "in progress" in low or "started" in low or "scheduled" in low or "ready" in low:
        return f"🔵 {text}"
    if "not started" in low or "not yet" in low:
        return f"⚪ {text}"
    return text


def margin_label(value) -> str:
    n = pd.to_numeric(value, errors="coerce")
    if pd.isna(n):
        return "⚪ N/A"
    n = int(round(float(n)))
    if n < 0:
        return f"🔴 {n} days"
    if n <= 3:
        return f"🟠 +{n} days" if n > 0 else "🟠 0 days"
    return f"🟢 +{n} days"


def due_label(days) -> str:
    n = pd.to_numeric(days, errors="coerce")
    if pd.isna(n):
        return "⚪ No due date"
    n = int(n)
    if n < 0:
        return f"🔴 {abs(n)} days overdue"
    if n <= 7:
        return f"🟠 Due in {n} days"
    return f"🔵 Due in {n} days"


def planning_status_bar():
    assumptions = st.session_state.get("assumptions") or {}
    planning_date = pd.Timestamp(assumptions.get("planning_date", pd.Timestamp.today())).normalize()
    target_days = int(assumptions.get("target_days", 55))
    handoff = int(assumptions.get("specialist_handoff_bdays", 2))
    info = st.session_state.get("schedule_info") or {}
    calculated_at = info.get("calculated_at")
    if calculated_at:
        try:
            last_calc = pd.Timestamp(calculated_at).strftime("%d %b %Y, %H:%M")
        except Exception:
            last_calc = str(calculated_at)
    else:
        last_calc = "Not yet calculated"

    schedule = st.session_state.get("schedule_result")
    dirty = bool(st.session_state.get("schedule_dirty"))
    if schedule is None:
        state = _chip("Schedule not generated", fg=GREY, bg=GREY_SOFT, dot=GREY)
    elif dirty:
        state = _chip("Recalculation required", fg=AMBER, bg=AMBER_SOFT, dot=AMBER)
    else:
        state = _chip("Schedule up to date", fg=GREEN, bg=GREEN_SOFT, dot=GREEN)

    st.markdown(
        f"""
        <div class="planning-status-bar">
            <strong style="color:{INK};margin-right:0.15rem;">Planning status</strong>
            {_chip('Planning date · ' + planning_date.strftime('%d %b %Y'), fg=PRIMARY_DARK, bg=PRIMARY_SOFT, dot=PRIMARY)}
            {_chip(f'Target · {target_days} days', fg=INK, bg=GREY_SOFT, dot=GREY)}
            {_chip(f'CT handoff · {handoff} working days', fg=INK, bg=GREY_SOFT, dot=GREY)}
            {_chip('Last calculated · ' + last_calc, fg=INK, bg=GREY_SOFT, dot=GREY)}
            {state}
        </div>
        """,
        unsafe_allow_html=True,
    )


def mini_stats(items: Iterable[tuple[str, object]]):
    html = "".join(
        f'<span class="mini-stat"><strong>{escape(str(label))}:</strong> {escape(str(value))}</span>'
        for label, value in items
    )
    st.markdown(f'<div class="mini-stat-row">{html}</div>', unsafe_allow_html=True)


def format_priority_display(value) -> str:
    """Display priority as a whole number without changing the numeric value used by the solver."""
    n = pd.to_numeric(value, errors="coerce")
    if pd.isna(n):
        return "N/A"
    return str(int(round(float(n))))


def queue_card(host, rank, trial, *, status="", due="", priority="", detail=""):
    host.markdown(
        f"""
        <div class="queue-card">
            <div style="display:flex;align-items:center;margin-bottom:0.6rem;">
                <span class="queue-rank">{escape(str(rank))}</span>
                <span style="font-size:1.02rem;font-weight:760;color:{INK};">{escape(str(trial))}</span>
            </div>
            <div style="margin-bottom:0.5rem;">{status_chip_html(status)}</div>
            <div style="font-size:0.81rem;color:{MUTED};line-height:1.55;">
                {escape(str(due))}<br>
                Priority: <strong style="color:{INK};">{escape(str(priority))}</strong>
                {('<br>' + escape(str(detail))) if detail else ''}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def trial_summary_card(*, trial, status, due=None, completion=None, margin=None, priority=None, queue_type=None):
    due_text = "N/A" if pd.isna(pd.to_datetime(due, errors="coerce")) else pd.Timestamp(due).strftime("%d %b %Y")
    comp_text = "N/A" if pd.isna(pd.to_datetime(completion, errors="coerce")) else pd.Timestamp(completion).strftime("%d %b %Y")
    margin_text = margin_label(margin)
    priority_text = format_priority_display(priority)
    st.markdown(
        f"""
        <div class="trial-card">
            <div class="section-kicker">Selected trial</div>
            <div style="display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;margin-bottom:0.8rem;">
                <span style="font-size:1.35rem;font-weight:780;color:{INK};">{escape(str(trial))}</span>
                {status_chip_html(status)}
            </div>
            <div style="display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:0.75rem;">
                <div><div style="font-size:0.75rem;color:{MUTED};">55-day due</div><strong>{escape(due_text)}</strong></div>
                <div><div style="font-size:0.75rem;color:{MUTED};">Expected completion</div><strong>{escape(comp_text)}</strong></div>
                <div><div style="font-size:0.75rem;color:{MUTED};">Margin</div><strong>{escape(margin_text)}</strong></div>
                <div><div style="font-size:0.75rem;color:{MUTED};">Priority / queue</div><strong>{escape(priority_text)}</strong><div style="font-size:0.75rem;color:{MUTED};">{escape(str(queue_type or ''))}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def dataframe_badge_style(df: pd.DataFrame, status_columns=None, margin_columns=None):
    """Return a Styler with semantic cell fills while keeping values accessible as text."""
    status_columns = [c for c in (status_columns or []) if c in df.columns]
    margin_columns = [c for c in (margin_columns or []) if c in df.columns]
    styler = df.style

    def status_css(value):
        text = str(value or "").lower()
        if "🔴" in text or "need" in text or "late" in text or "blocked" in text or "missing" in text:
            return f"background-color:{RED_SOFT};color:{RED};font-weight:600;"
        if "🟠" in text or "await" in text or "overdue" in text or "attention" in text:
            return f"background-color:{AMBER_SOFT};color:{AMBER};font-weight:600;"
        if "🟢" in text or "completed" in text or "on time" in text:
            return f"background-color:{GREEN_SOFT};color:{GREEN};font-weight:600;"
        if "🔵" in text or "in progress" in text or "started" in text or "scheduled" in text:
            return f"background-color:{PRIMARY_SOFT};color:{PRIMARY_DARK};font-weight:600;"
        if "⚪" in text or "n/a" in text or "not started" in text:
            return f"background-color:{GREY_SOFT};color:{GREY};"
        return ""

    for col in status_columns + margin_columns:
        try:
            styler = styler.map(status_css, subset=[col])
        except AttributeError:  # pandas < 2.1 fallback
            styler = styler.applymap(status_css, subset=[col])
    return styler
