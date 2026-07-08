import streamlit as st
from datetime import date
from components.planning.icons import (
    get_commitment_icon,
    get_income_icon
)
from components.planning.template_dialog import (
    show_template_dialog
)
from components.planning.template_section import (
    render_template_table
)
from components.planning.activity_table import (
    render_activity_row
)
from components.planning.close_month_dialog import (
    show_close_month_dialog
)
from db.accounts import get_accounts
from db.planning import (
    add_commitment,
    add_income_template,
    delete_commitment,
    delete_income_template,
    finalize_month,
    get_commitments,
    get_cycle,
    get_cycle_planning_summary,
    get_income_templates,
    get_planning_activity_statuses,
    save_income_status,
    save_obligation_status,
    update_commitment,
    update_income_template
)
from db.financial_cycles import (
    build_cycle_navigation_options,
    close_active_cycle,
    derive_cycle_status,
    format_cycle_range,
    get_cycle_for_date,
)

def get_day_suffix(day):

    if 10 <= day % 100 <= 20:
        return "th"

    return {
        1: "st",
        2: "nd",
        3: "rd"
    }.get(day % 10, "th")


def show_planning(vault_id):

    income_templates = get_income_templates(
        vault_id
    )

    commitments = get_commitments(vault_id)
 
    title_col, nav_col = st.columns(
    [3.8,2.2],
    vertical_alignment="center"
)
    current_cycle = get_cycle_for_date(
        vault_id,
        date.today().isoformat()
    )
    cycle_options = build_cycle_navigation_options(vault_id)

    if "planning_selected_cycle_start" not in st.session_state:
        st.session_state.planning_selected_cycle_start = (
            current_cycle.start_iso
        )

    cycle_keys = [
        option["key"]
        for option in cycle_options
    ]

    if st.session_state.planning_selected_cycle_start not in cycle_keys:
        st.session_state.planning_selected_cycle_start = (
            current_cycle.start_iso
        )

    selected_index = cycle_keys.index(
        st.session_state.planning_selected_cycle_start
    )

    with title_col:

        st.markdown("""
        <div class="planning-header">
            <h2>📅 Financial Cycle</h2>
            <p>Plan, execute and close your financial period.</p>
        </div>
        """, unsafe_allow_html=True)
    with nav_col:
        nav_left, nav_mid, nav_right = st.columns(
            [1.1, 2.3, 1.1],
            gap="small",
            vertical_alignment="center"
        )

        with nav_left:
            if st.button(
                "Previous Cycle",
                key="cycle_prev",
                use_container_width=True,
                disabled=selected_index == 0
            ):
                st.session_state.planning_selected_cycle_start = (
                    cycle_options[selected_index - 1]["key"]
                )
                st.rerun()

        with nav_mid:
            selected_cycle_key = st.selectbox(
                "Current Cycle",
                options=cycle_keys,
                index=selected_index,
                format_func=lambda key: next(
                    option["label"]
                    for option in cycle_options
                    if option["key"] == key
                ),
                label_visibility="collapsed"
            )
            if selected_cycle_key != (
                st.session_state.planning_selected_cycle_start
            ):
                st.session_state.planning_selected_cycle_start = (
                    selected_cycle_key
                )
                st.rerun()

        with nav_right:
            if st.button(
                "Next Cycle",
                key="cycle_next",
                use_container_width=True,
                disabled=selected_index == len(cycle_options) - 1
            ):
                st.session_state.planning_selected_cycle_start = (
                    cycle_options[selected_index + 1]["key"]
                )
                st.rerun()

        selected_context = get_cycle_for_date(
            vault_id,
            st.session_state.planning_selected_cycle_start
        )
        selected_cycle_label = format_cycle_range(
            selected_context.start_date,
            selected_context.end_date
        )

        st.markdown(
            f"""
            <div class="glass-month">
                {selected_cycle_label}
            </div>
            """,
            unsafe_allow_html=True
        )

    selected_date = selected_context.start_date
    selected_cycle_key = selected_context.start_iso

    if st.session_state.get("last_close_dialog_cycle") != selected_cycle_key:

        for key in list(st.session_state.keys()):

            if key.startswith("close_"):
                del st.session_state[key]

        st.session_state.last_close_dialog_cycle = selected_cycle_key

    cycle = get_cycle(
        vault_id,
        selected_date.month,
        selected_date.year
    )
    cycle_month = cycle[2]
    cycle_year = cycle[3]
    cycle_start = date.fromisoformat(cycle[5])
    cycle_end = date.fromisoformat(cycle[6])
    cycle_label = format_cycle_range(
        cycle_start,
        cycle_end,
        include_year=True
    )

    cycle_summary = get_cycle_planning_summary(
        vault_id,
        cycle_month,
        cycle_year,
        cycle_start.isoformat(),
        cycle_end.isoformat()
    )
    activity_statuses = get_planning_activity_statuses(
        vault_id,
        cycle_month,
        cycle_year
    )

    income = cycle_summary["income_planned"]
    total_commitments = cycle_summary["commitments_planned"]
    remaining_commitments = cycle_summary["remaining_commitments"]

    current_date = date.today()

    total_days = max((cycle_end - cycle_start).days + 1, 1)
    if cycle_start <= current_date <= cycle_end:
        days_left = max((cycle_end - current_date).days + 1, 0)
        days_completed = min(
            max((current_date - cycle_start).days, 0),
            total_days
        )
    elif current_date > cycle_end:
        days_left = 0
        days_completed = total_days
    else:
        days_left = total_days
        days_completed = 0

    progress_percent = int(
        days_completed / total_days * 100
    )

    started_on = cycle_start.strftime("%d %b %Y")

    cycle_status = derive_cycle_status(
        cycle_start,
        cycle_end,
        current_date
    )
    is_read_only = False
    pill = cycle_status

    upcoming_commitments = 0
    for commitment in commitments:
        status_row = activity_statuses.get(
            ("commitment", commitment[0])
        )
        if not status_row or status_row[1] in [
            "PENDING",
            "CARRIED_FORWARD"
        ]:
            upcoming_commitments += 1

    hero_metrics = [
        (
            "Income Planned",
            f"&#8377;{cycle_summary['income_planned']:,.0f}",
            "success"
        ),
        (
            "Income Received",
            f"&#8377;{cycle_summary['income_received']:,.0f}",
            "success"
        ),
        (
            "Remaining Commitments",
            f"&#8377;{cycle_summary['remaining_commitments']:,.0f}",
            "danger"
        ),
        (
            "Projected Savings",
            f"&#8377;{cycle_summary['projected_savings']:,.0f}",
            "accent"
        )
    ]

    hero_metric_html = "".join(
        f"""<div class="cycle-hero-metric">
                <span>{label}</span>
                <strong class="{tone}">{value}</strong>
            </div>"""
        for label, value, tone in hero_metrics
    )

    st.markdown(
    f"""<div class="cycle-hero">
        <div class="cycle-hero-main">
            <div class="cycle-hero-title-row">
                <div>
                    <div class="cycle-eyebrow">Financial Cycle</div>
                    <div class="cycle-title">{cycle_label}</div>
                </div>
                <div class="status-pill">{pill}</div>
            </div>
            <div class="cycle-progress-track">
                <div style="width:{progress_percent}%"></div>
            </div>
            <div class="cycle-hero-facts">
                <div>
                    <span>Started</span>
                    <strong>{started_on}</strong>
                </div>
                <div>
                    <span>Completed</span>
                    <strong>{days_completed}/{total_days} days</strong>
                </div>
                <div>
                    <span>Remaining</span>
                    <strong class="success">{days_left} days</strong>
                </div>
                <div>
                    <span>Progress</span>
                    <strong>{progress_percent}%</strong>
                </div>
            </div>
        </div>
        <div class="cycle-hero-side">
            <div class="cycle-hero-metrics">
                {hero_metric_html}
            </div>
            <div class="cycle-hero-upcoming">
                <span>Upcoming Commitments</span>
                <strong>{upcoming_commitments}</strong>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

    st.markdown("<br>", unsafe_allow_html=True)

    if pill == "Completed":
        st.warning(f"""**{cycle_label}** is completed.""")

    st.markdown(
        """
        <div class="section-main-title">Planning Summary</div>
        <div class="section-subtitle">
            Selected financial cycle snapshot.
        </div>
        """,
        unsafe_allow_html=True
    )

    metric_values = [
        ("Income Planned", cycle_summary["income_planned"]),
        ("Income Received", cycle_summary["income_received"]),
        ("Commitments Planned", cycle_summary["commitments_planned"]),
        ("Commitments Completed", cycle_summary["commitments_completed"]),
        ("Remaining Commitments", cycle_summary["remaining_commitments"]),
        ("Savings Goal", cycle_summary["savings_goal"]),
        ("Projected Savings", cycle_summary["projected_savings"])
    ]

    for row_start in range(0, len(metric_values), 4):
        columns = st.columns(4)
        for column, (label, amount) in zip(
            columns,
            metric_values[row_start:row_start + 4]
        ):
            with column:
                st.metric(
                    label,
                    f"₹{amount:,.0f}"
                )

    empty_messages = []
    if cycle_summary["income_planned"] <= 0:
        empty_messages.append("No income planned for this cycle.")
    if cycle_summary["commitments_planned"] <= 0:
        empty_messages.append("No commitments added.")
    if cycle_summary["expenses"] <= 0:
        empty_messages.append("No transactions yet.")

    if empty_messages:
        st.info(" ".join(empty_messages))
    
    ##########################################################################
    # FINANCIAL CYCLE ACTIVITIES
    ##########################################################################

    with st.container(border=True):

        top_left = st.container()

        with top_left:

            st.markdown(f"""
            <div class="section-main-title">
                Financial Cycle Activities ({cycle_label})
            </div>

            <div class="section-subtitle">
                Track actuals and mark payments as you complete them.
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""
        <div class="monthly-obligations-section">
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="obligation-header">
            <div>Obligation</div>
            <div>Expected</div>
            <div>Actual</div>
            <div>Due Day</div>
            <div>Status</div>
            <div>Actions</div>
        </div>
        """, unsafe_allow_html=True)

        activities = []

        # ----------------------------
        # Income Activities
        # ----------------------------

        for row in income_templates:

            activities.append({
                "type": "income",
                "id": row[0],
                "name": row[1],
                "expected": row[2],
                "due_day": row[3],
                "icon": "💰"
            })

        # ----------------------------
        # Commitment Activities
        # ----------------------------

        for row in commitments:

            activities.append({
                "type": "commitment",
                "id": row[0],
                "name": row[1],
                "expected": row[2],
                "due_day": row[3],
                "icon": get_commitment_icon(row[1])
            })

        # Sort by due day
        activities.sort(
            key=lambda x: x["due_day"]
        )

        month_name = cycle_start.strftime("%b")

        for activity in activities:

            if activity["type"] == "income":

                status_row = activity_statuses.get(
                    ("income", activity["id"])
                )

                if status_row:
                    activity_status = status_row[1]
                    effective_expected = (
                        status_row[0]
                        if (
                            status_row[0] is not None
                            and activity_status != "CANCELLED"
                        )
                        else activity["expected"]
                    )
                    actual = (
                        status_row[0]
                        if activity_status == "RECEIVED"
                        else effective_expected
                    )
                else:
                    activity_status = "PENDING"
                    effective_expected = activity["expected"]
                    actual = effective_expected

                activity["effective_expected"] = effective_expected

                render_activity_row(

                    item_id=activity["id"],
                    icon=activity["icon"],
                    name=activity["name"],
                    expected=effective_expected,
                    actual=actual,
                    due_day=activity["due_day"],
                    month_name=month_name,
                    status=activity_status,
                    complete_text="Received",
                    complete_status="RECEIVED",
                    input_prefix="income",
                    read_only=is_read_only,

                    complete_callback=lambda amount, i=activity["id"]:
                        save_income_status(
                            i,
                            cycle_month,
                            cycle_year,
                            amount,
                            "RECEIVED"
                        ),

                    cancel_callback=lambda i=activity["id"]:
                        save_income_status(
                            i,
                            cycle_month,
                            cycle_year,
                            0,
                            "CANCELLED"
                        ),
                )

            else:

                status_row = activity_statuses.get(
                    ("commitment", activity["id"])
                )

                if status_row:
                    activity_status = status_row[1]
                    effective_expected = (
                        status_row[0]
                        if (
                            status_row[0] is not None
                            and activity_status != "CANCELLED"
                        )
                        else activity["expected"]
                    )
                    actual = (
                        status_row[0]
                        if activity_status == "PAID"
                        else effective_expected
                    )
                else:
                    activity_status = "PENDING"
                    effective_expected = activity["expected"]
                    actual = effective_expected

                activity["effective_expected"] = effective_expected

                render_activity_row(

                    item_id=activity["id"],
                    icon=activity["icon"],
                    name=activity["name"],
                    expected=effective_expected,
                    actual=actual,
                    due_day=activity["due_day"],
                    month_name=month_name,
                    status=activity_status,
                    complete_text="Paid",
                    complete_status="PAID",
                    input_prefix="commitment",

                    complete_callback=lambda amount, i=activity["id"]:
                        save_obligation_status(
                            i,
                            cycle_month,
                            cycle_year,
                            amount,
                            "PAID"
                        ),

                    cancel_callback=lambda i=activity["id"]:
                        save_obligation_status(
                            i,
                            cycle_month,
                            cycle_year,
                            0,
                            "CANCELLED"
                        ),
                    read_only=is_read_only
                )


    ##########################################################################
    # RECURRING INCOME
    ##########################################################################

    with st.container(border=True):

        header_col1, header_col2 = st.columns([4,1])

        with header_col1:

            st.markdown("""
            <div class="section-main-title">
                Recurring Income
            </div>

            <div class="section-subtitle">
                Expected income sources for each financial cycle.
            </div>
            """, unsafe_allow_html=True)

        with header_col2:

            if st.button(
                "Add Income",
                use_container_width=True, disabled=is_read_only
            ):
                st.session_state.show_income_form = True

        if st.session_state.get("show_income_form") and not is_read_only:
            st.session_state.show_income_form = False

            @st.dialog("Add Income Template")
            def add_income_modal():

                accounts = get_accounts(vault_id)

                if not accounts:
                    st.warning(
                        "Create an account before adding recurring income."
                    )
                    if st.button(
                        "Close",
                        use_container_width=True
                    ):
                        st.session_state.show_income_form = False
                        st.rerun()
                    return

                account_map = {
                    a[1]: a[0]
                    for a in accounts
                }

                name = st.text_input(
                    "Income Name"
                )
                
                amount = st.number_input(
                    "Amount",
                    min_value=0.0,
                    step=0.01,
                    value=None,
                    placeholder="Enter Amount",
                    format="%.2f"
                )

                due_day = st.number_input(
                    "Due Day",
                    min_value=1,
                    max_value=31,
                    value=1
                )

                selected_account = st.selectbox(
                    "Deposit Account",
                    list(account_map.keys())
                )

                save_col, cancel_col = st.columns(2)

                with save_col:
                    save_clicked = st.button(
                        "💾 Save",
                        use_container_width=True
                    )

                with cancel_col:
                    cancel_clicked = st.button(
                        "Cancel",
                        use_container_width=True
                    )

                if cancel_clicked:

                    st.session_state.show_income_form = False

                    st.rerun()

                if save_clicked:

                    if not name.strip():

                        st.error(
                            "Income Name is required."
                        )

                        st.stop()

                    if amount is None:

                        st.error(
                            "Amount is required."
                        )

                        st.stop()

                    if amount <= 0:

                        st.error(
                            "Amount must be greater than 0."
                        )

                        st.stop()

                    try:
                        add_income_template(
                            vault_id,
                            name.strip(),
                            amount,
                            due_day,
                            account_map[selected_account]
                        )
                    except ValueError as error:
                        st.error(str(error))
                        st.stop()

                    st.session_state.show_income_form = False

                    st.rerun()

            add_income_modal()

        render_template_table(
            rows=income_templates,
            icon_function=get_income_icon,
            action_prefix="income", read_only=is_read_only
        )
        selected_income_id = st.session_state.get(
            "edit_income_id"
        )

        if selected_income_id:
            st.session_state.edit_income_id = None

            selected_income = next(
                (
                    i
                    for i in income_templates
                    if i[0] == selected_income_id
                ),
                None
            )

            if selected_income:
                income_id = selected_income[0]
                current_name = selected_income[1]
                current_amount = selected_income[2]
                current_due_day = selected_income[3]
                current_account_id = selected_income[5]
                accounts = get_accounts(vault_id)
                show_template_dialog(
                    title="Edit Income",
                    name_label="Income Name",
                    account_label="Deposit Account",
                    current_name=current_name,
                    current_amount=current_amount,
                    current_due_day=current_due_day,
                    current_account_id=current_account_id,
                    accounts=accounts,
                    session_key="edit_income_id",
                    on_save=lambda name, amount, due_day, account_id:
                        update_income_template(
                            income_id,
                            name,
                            amount,
                            due_day,
                            account_id
                        ),
                    on_delete=lambda:
                        delete_income_template(
                            income_id
                        ),
                    read_only=is_read_only
                )

    ##########################################################################
    # RECURRING COMMITTMENTS
    ##########################################################################

    with st.container(border=True):

        header_col1, header_col2 = st.columns([4,1])

        with header_col1:

            st.markdown("""
            <div class="section-main-title">
                Recurring Commitments
            </div>

            <div class="section-subtitle">
                These create obligations for each financial cycle.
            </div>
            """, unsafe_allow_html=True)

        with header_col2:

            if st.button(
                "Add Commitment",
                use_container_width=True, disabled=is_read_only
            ):
                st.session_state.show_template_form = True
            
            if st.session_state.get("show_template_form") and not is_read_only:
                st.session_state.show_template_form = False

                @st.dialog("Add Commitment Template")
                def add_template_modal():

                    accounts = get_accounts(vault_id)

                    if not accounts:
                        st.warning(
                            "Create an account before adding a commitment."
                        )
                        if st.button(
                            "Close",
                            use_container_width=True
                        ):
                            st.session_state.show_template_form = False
                            st.rerun()
                        return

                    account_map = {
                        account[1]: account[0]
                        for account in accounts
                    }

                    name = st.text_input(
                        "Commitment Name"
                    )

                    amount = st.number_input(
                        "Amount",
                        min_value=0.0,
                        step=0.01,
                        value=None,
                        placeholder="Enter Amount",
                        format="%.2f"
                    )

                    due_day = st.number_input(
                        "Due Day",
                        min_value=1,
                        max_value=31,
                        value=1
                    )

                    selected_account = st.selectbox(
                        "Account",
                        list(account_map.keys())
                    )
                    error_placeholder = st.empty()
                    save_col, cancel_col = st.columns(2)

                    with save_col:

                        if st.button(
                            "💾 Save",
                            use_container_width=True
                        ):

                            if not name.strip():

                                error_placeholder.error(
                                    "Commitment Name is required."
                                )

                                st.stop()

                            if amount is None:
                                error_placeholder.error(
                                    "Amount is required."
                                )

                                st.stop()
                            if amount <= 0:
                                error_placeholder.error(
                                    "Amount must be greater than 0."
                                )
                                st.stop()

                            try:
                                add_commitment(
                                    vault_id,
                                    name.strip(),
                                    amount,
                                    due_day,
                                    account_map[selected_account]
                                )
                            except ValueError as error:
                                error_placeholder.error(str(error))
                                st.stop()

                            st.session_state.show_template_form = False

                            st.rerun()

                    with cancel_col:

                        if st.button(
                            "✖ Cancel",
                            use_container_width=True
                        ):

                            st.session_state.show_template_form = False

                            st.rerun()

                add_template_modal()
                st.markdown("<br>", unsafe_allow_html=True)

        render_template_table(

            rows=commitments,

            icon_function=get_commitment_icon,

            action_prefix="commitment", read_only=is_read_only

        )
        selected_id = st.session_state.get(
            "edit_commitment_id"
        )

        if selected_id and not is_read_only:
            st.session_state.edit_commitment_id = None

            selected_commitment = next(
                (
                    c for c in commitments
                    if c[0] == selected_id
                ),
                None
            )

            if selected_commitment:
                commitment_id = selected_commitment[0]
                current_name = selected_commitment[1]
                current_amount = selected_commitment[2]
                current_due_day = selected_commitment[3]
                current_account_id = selected_commitment[5]
                accounts = get_accounts(vault_id)
                show_template_dialog(
                    title="Edit Commitment",
                    name_label="Commitment Name",
                    account_label="Account",
                    current_name=current_name,
                    current_amount=current_amount,
                    current_due_day=current_due_day,
                    current_account_id=current_account_id,
                    accounts=accounts,
                    session_key="edit_commitment_id",
                    on_save=lambda name,
                                    amount,
                                    due_day,
                                    account_id:
                        update_commitment(
                            commitment_id,
                            name,
                            amount,
                            due_day,
                            account_id
                        ),
                    on_delete=lambda:

                        delete_commitment(
                            commitment_id
                        ),
                    read_only=is_read_only
                )

    ##########################################################################
    # CLOSE CYCLE
    ##########################################################################

    close_disabled = (
        cycle_status != "Current"
    )

    if st.button(
        "Close Cycle",
        use_container_width=True,
        disabled=close_disabled
    ):

        pending = []

        for activity in activities:

            if activity["type"] == "income":

                status_row = activity_statuses.get(
                    ("income", activity["id"])
                )

                if (
                    status_row is None
                    or status_row[1] in [
                        "PENDING",
                        "CARRIED_FORWARD"
                    ]
                ):

                    pending.append({
                        "id": activity["id"],
                        "type": "income",
                        "name": activity["name"],
                        "expected": activity.get(
                            "effective_expected",
                            activity["expected"]
                        ),
                        "icon": activity["icon"],
                        "default_action": None
                    })

            else:

                status_row = activity_statuses.get(
                    ("commitment", activity["id"])
                )

                if (
                    status_row is None
                    or status_row[1] in [
                        "PENDING",
                        "CARRIED_FORWARD"
                    ]
                ):

                    pending.append({
                        "id": activity["id"],
                        "type": "commitment",
                        "name": activity["name"],
                        "expected": activity.get(
                            "effective_expected",
                            activity["expected"]
                        ),
                        "icon": activity["icon"],
                        "default_action": None
                    })

        def handle_close_cycle(items):

            finalize_month(
                vault_id,
                cycle_month,
                cycle_year,
                items
            )
            close_active_cycle(vault_id)
            current_cycle = get_cycle_for_date(
                vault_id,
                date.today().isoformat()
            )
            st.session_state.planning_selected_cycle_start = (
                current_cycle.start_iso
            )
            st.success("Cycle closed successfully!")
            st.rerun()

        show_close_month_dialog(
            month_name=cycle_label,
            pending_items=pending,
            on_confirm=handle_close_cycle
        )
