            if pd.isna(remaining) or float(remaining) <= 0:
                continue
            start = pd.to_datetime(r.get(sc), errors="coerce")
            end = pd.to_datetime(r.get(ec), errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue
            lane = f"{rank}. {trial} · {workstream}" if view_mode == "By trial" else f"{workstream} · {rank}. {trial}"
            rows.append({
                "Lane": lane,
                "Trial": trial,
                "Rank": rank,
                "Workstream": workstream,
                "Workstream order": workstream_order[workstream],
                "Segment type": "Recommended remaining work",
                "Start": start,
                "End": end,
                "Detail": f"{int(remaining)} remaining working day(s)",
            })

    if rows:
        timeline = pd.DataFrame(rows)
        if view_mode == "By trial":
            timeline = timeline.sort_values(["Rank", "Workstream order", "Start"])
        else:
            timeline = timeline.sort_values(["Workstream order", "Rank", "Start"])
        lane_order = timeline["Lane"].drop_duplicates().tolist()
        fig = px.timeline(
            timeline,
            x_start="Start",
            x_end="End",
            y="Lane",
            color="Segment type",
            text="Workstream",
            hover_data=["Trial", "Workstream", "Detail"],
            category_orders={"Lane": lane_order},
            color_discrete_map={
                "Observed progress": ui.GREEN_SOFT,
                "Recommended remaining work": ui.PRIMARY_SOFT,
            },
        )
        fig.update_traces(textposition="inside", textfont_color=ui.INK)
        fig.update_yaxes(autorange="reversed", title=None)
        fig.add_vline(x=planning_date, line_width=1.5, line_dash="dash", line_color=ui.GREY)
        fig.update_layout(
            height=max(520, 24 * timeline["Lane"].nunique() + 170),
            legend_title_text="",
            bargap=0.14,
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Planning-date divider: {planning_date.strftime('%d/%m/%Y')}. Default CT → specialist handoff is {int(st.session_state.assumptions.get('specialist_handoff_bdays', 2))} working days."
        )
    else:
        st.caption("No observed or recommended workstream dates are available for the selected trials.")

    with st.expander("Temporary capacity reductions applied", expanded=False):
        exceptions = st.session_state.assumptions.get("capacity_exceptions", [])
        if exceptions:
            ex_df = pd.DataFrame(exceptions).rename(columns={
                "workstream": "Workstream", "start_date": "From", "end_date": "To",
                "available_capacity": "Available capacity", "note": "Reason",
            })
            for col in ["From", "To"]:
                if col in ex_df.columns:
                    ex_df[col] = ex_df[col].map(core.format_date_for_display)
            st.dataframe(ex_df, use_container_width=True, hide_index=True)
        else:
            st.caption("None")

with export_tab:
    st.markdown("#### Export the current recommendation")
    export_schedule = core.sync_schedule_metadata(schedule, st.session_state.trial_table)
    export_cols = [
        "final_rank", "trial_id", "effective_trial_status", "clock_start", "pharmacy_notified_date",
        "due_date_rec", "manual_rank", "final_decision", "ct_complexity", "ct_duration_bdays",
        "CT_start_rec", "CT_end_rec", "CT_capacity_end_rec", "aseptic_duration_bdays", "Aseptic_start_rec", "Aseptic_end_rec",
        "epma_complexity", "epma_duration_bdays", "ePMA_start_rec", "ePMA_end_rec",
        "completion_rec", "margin_days", "schedule_status", "pharmacy_note",
    ]
    export_df = export_schedule[[c for c in export_cols if c in export_schedule.columns]].copy()
    export_df = export_df.rename(columns={
        "final_rank": "Rank", "trial_id": "Trial", "effective_trial_status": "Status",
        "clock_start": "55-day clock start", "pharmacy_notified_date": "Pharmacy notified",
        "due_date_rec": "55-day due", "manual_rank": "Manual Rank", "final_decision": "Final decision",
        "ct_complexity": "CT Complexity", "ct_duration_bdays": "CT days",
        "CT_start_rec": "CT start", "CT_end_rec": "CT active-work end", "CT_capacity_end_rec": "CT capacity held until",
        "aseptic_duration_bdays": "Aseptic days", "Aseptic_start_rec": "Aseptic start", "Aseptic_end_rec": "Aseptic end",
        "epma_complexity": "ePMA Complexity", "epma_duration_bdays": "ePMA days",
        "ePMA_start_rec": "ePMA start", "ePMA_end_rec": "ePMA end",
        "completion_rec": "Expected completion", "margin_days": "Margin days",
        "schedule_status": "Schedule status", "pharmacy_note": "Pharmacy Note",
    })
    export_date_cols = [
        "55-day clock start", "Pharmacy notified", "55-day due", "CT start", "CT active-work end", "CT capacity held until",
        "Aseptic start", "Aseptic end", "ePMA start", "ePMA end", "Expected completion",
    ]
    csv_df = _uk_date_strings(export_df, export_date_cols)
    st.download_button(
        "Download schedule CSV",
        csv_df.to_csv(index=False).encode("utf-8-sig"),
        "pharmacy_schedule.csv",
        "text/csv",
        use_container_width=True,
    )
    excel_bytes = core.dataframe_to_excel_bytes(
        export_df,
        sheet_name="Recommended Schedule",
        date_columns=export_date_cols,
        preferred_widths={"Trial": 28, "Final decision": 26, "Pharmacy Note": 55},
    )
    st.download_button(
        "Download schedule Excel",
        excel_bytes,
        "pharmacy_schedule.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

core.render_page_navigation(
    previous_page="pages/02_Trial_Prioritisation.py",
    next_page="pages/04_Saved_Work.py",
    previous_label="Prioritise",
    next_label="Review",
)
