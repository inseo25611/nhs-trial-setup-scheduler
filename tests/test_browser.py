
"""Automated browser tests for the NHS Streamlit scheduler."""

import os
from playwright.sync_api import expect

APP_URL = os.getenv("NHS_TEST_URL", "http://localhost:8501")


def go_to(page, name):
    """Navigate to a page and wait for it to load."""
    page.get_by_role("link", name=name, exact=True).click()


def load_sample_data(page):
    """Load synthetic trials and confirm the data is ready."""

    page.goto(APP_URL)

    # Go to the Trials page.
    go_to(page, "Trials")

    expect(
        page.get_by_role("heading", name="Trials & Data Quality")
    ).to_be_visible(timeout=30000)

    # Load the synthetic trial portfolio.
    load_button = page.get_by_role(
        "button", name="Load synthetic sample data"
    )

    expect(load_button).to_be_visible(timeout=30000)
    load_button.click()

    # Wait for the ACTUAL loaded workspace name.
    expect(
        page.get_by_text("Current workspace:", exact=False)
    ).to_contain_text(
        "Synthetic sample portfolio", timeout=30000
    )


def test_load_synthetic_portfolio(page):
    """Check that the sample portfolio loads successfully."""

    load_sample_data(page)


def test_capacity_form_and_schedule_generation(page):
    """Check capacity settings and schedule generation."""

    # Step 1: Load the data first.
    load_sample_data(page)

    # Step 2: Open Capacity.
    go_to(page, "Capacity")

    expect(
        page.get_by_role(
            "heading", name="Capacity & Assumptions"
        )
    ).to_be_visible(timeout=30000)

    # Change CT capacity to 4.
    capacity_input = page.get_by_label(
        "CT capacity", exact=True
    )

    capacity_input.fill("4")

    page.get_by_role(
        "button", name="Save core assumptions"
    ).click()

    # Step 3: Open Schedule.
    go_to(page, "Schedule")

    expect(
        page.get_by_role(
            "heading", name="Recommended Schedule"
        )
    ).to_be_visible(timeout=30000)

    # Check that data is still available.
    no_data = page.get_by_text(
        "No trial data has been loaded", exact=False
    )

    if no_data.count() > 0 and no_data.is_visible():
        page.screenshot(
            path="schedule_debug.png",
            full_page=True
        )
        raise AssertionError(
            "Sample data was loaded in Trials, "
            "but disappeared before Schedule. "
            "Check Streamlit session state."
        )

    # Step 4: Generate the schedule.
    generate_button = page.get_by_role(
        "button", name="Generate / recalculate"
    )

    expect(generate_button).to_be_visible(timeout=30000)
    generate_button.click()

    # Step 5: Check calculation status.
    expect(
        page.get_by_text(
            "The current schedule matches the latest saved inputs."
        )
    ).to_be_visible(timeout=120000)

    # Step 6: Check that capacity remains saved.
    go_to(page, "Capacity")

    expect(
        page.get_by_label("CT capacity", exact=True)
    ).to_have_value("4")
