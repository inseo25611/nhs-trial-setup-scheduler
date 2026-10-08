from pathlib import Path
import importlib.util
import sys

import streamlit as st

# Always load the nhs_core.py that sits next to this app.py.
APP_DIR = Path(__file__).resolve().parent
CORE_PATH = APP_DIR / "nhs_core.py"


def _load_local_core():
    if not CORE_PATH.exists():
        raise FileNotFoundError(f"Expected nhs_core.py at {CORE_PATH}")
    spec = importlib.util.spec_from_file_location("nhs_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create an import spec for {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nhs_core"] = module
    spec.loader.exec_module(module)
    return module


core = _load_local_core()

_REQUIRED_CORE_API = [
    "initialise_state",
    "render_saved_work_sidebar",
    "inspect_operational_file",
]
_missing = [name for name in _REQUIRED_CORE_API if not hasattr(core, name)]
if _missing:
    st.error(
        "The local nhs_core.py is incomplete for this app version. "
        f"Missing: {', '.join(_missing)}"
    )
    st.caption(f"Loaded core file: {getattr(core, '__file__', CORE_PATH)}")
    st.stop()

st.set_page_config(
    page_title="Clinical Trial Pharmacy Planning Tool",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

import ui_components as ui

core.initialise_state()
ui.apply_global_styles()

# Workflow-oriented navigation: portfolio → data → capacity → prioritisation → schedule → review.
pages = [
    st.Page("pages/01_Portfolio_Overview.py", title="Overview", icon="🏠", default=True),
    st.Page("pages/06_Data_Assumptions.py", title="Trials", icon="🧪"),
    st.Page("pages/05_Capacity_Planning.py", title="Capacity", icon="⚙️"),
    st.Page("pages/02_Trial_Prioritisation.py", title="Prioritise", icon="🎯"),
    st.Page("pages/03_Recommended_Schedule.py", title="Schedule", icon="📅"),
    st.Page("pages/04_Saved_Work.py", title="Review", icon="✅"),
]

page = st.navigation(pages, position="top")

# Build the top navigation first, then render the shared planning strip beneath it.
ui.planning_status_bar()
page.run()

# Keep recovery controls available without interrupting the main workflow.
core.render_saved_work_sidebar()
