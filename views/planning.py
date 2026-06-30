import streamlit as st
from datetime import datetime
from datetime import date
import calendar
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
    create_cycle,
    delete_commitment,
    delete_income_template,
    finalize_month,
    get_commitments,
    get_cycle,
    get_income_status,
    get_income_templates,
    get_monthly_planning_totals,
    get_next_month,
    get_obligation_status,
    save_income_status,
    save_obligation_status,
    update_commitment,
    update_income_template
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
    current_year = datetime.now().year
    months = []

    current_year = datetime.now().year

    for year in range(
        current_year - 1,
        current_year + 2
    ):

        for month in range(1, 13):

            months.append(

                datetime(
                    year,
                    month,
                    1
                ).strftime("%B %Y")

            )

    current_month = datetime.now().strftime("%B %Y")

    if current_month in months:
        default_index = months.index(current_month)
    else:
        default_index = 0

    if "month_selector" not in st.session_state:
        st.session_state.month_selector = months[default_index]

    with title_col:

        st.markdown("""
        <div class="planning-header">
            <h2>📅 Monthly Cycle</h2>
            <p>Plan, execute and close your month.</p>
        </div>
        """, unsafe_allow_html=True)

    with nav_col:
        current_index = months.index(
            st.session_state.month_selector
        )

        nav_left, nav_mid, nav_right = st.columns(
            [0.9, 3.2, 0.9],
            gap="small",
            vertical_alignment="center"
        )

        with nav_left:

            if st.button(
                "❮",
                key="month_prev",
                use_container_width=True,
                disabled=current_index == 0
            ):

                st.session_state.month_selector = months[
                    current_index - 1
                ]

                st.rerun()

        with nav_mid:

            st.markdown(
                f"""
                <div class="glass-month">
                    {st.session_state.month_selector}
                </div>
                """,
                unsafe_allow_html=True
            )

        with nav_right:

            if st.button(
                "❯",
                key="month_next",
                use_container_width=True,
                disabled=current_index == len(months)-1
            ):

                st.session_state.month_selector = months[
                    current_index + 1
                ]

                st.rerun()

    selected_month = st.session_state.month_selector

    selected_date = datetime.strptime(
        selected_month,
        "%B %Y"
    )
        
    if st.session_state.get("last_close_dialog_month") != selected_month:

        for key in list(st.session_state.keys()):

            if key.startswith("close_"):
                del st.session_state[key]

        st.session_state.last_close_dialog_month = selected_month

    create_cycle(
    vault_id,
    selected_date.month,
    selected_date.year)

    monthly_totals = get_monthly_planning_totals(
        vault_id,
        selected_date.month,
        selected_date.year
    )

    income = monthly_totals["income"]
    total_commitments = monthly_totals[
        "planned_commitments"
    ]
    remaining_commitments = monthly_totals[
        "remaining_commitments"
    ]

    selected_month_date  = selected_date.date()

    days_in_month = calendar.monthrange(
        selected_month_date.year,
        selected_month_date.month
    )[1]

    current_date = date.today()

    if (
        selected_date.year == current_date.year
        and
        selected_date.month == current_date.month
    ):
        days_left = (
            days_in_month
            - current_date.day
        )
    else:
        days_left = days_in_month

    month_start = selected_month_date.replace(day=1)

    started_on = month_start.strftime("%d %b %Y")
    cycle = get_cycle(
        vault_id,
        selected_date.month,
        selected_date.year
    )

    cycle_status = cycle[4]
    is_read_only = cycle_status in ["PLANNED", "CLOSED"]
    if cycle_status == "ACTIVE":
        pill = "🟢 Active"

    elif cycle_status == "PLANNED":
        pill = "🟣 Planned"

    elif cycle_status == "CLOSED":
        pill = "🔒 Closed"

    else:
        pill = "⚪ Unknown"

    st.markdown(
    f"""<div class="cycle-hero">
        <div class="cycle-status">
            <div class="status-row">
                <div class="cycle-label">Status</div>
                <div class="status-pill">{pill}</div>
            </div>
            <div class="cycle-meta">
                <span class="cycle-label">Started</span>
                <span class="cycle-meta-value">{started_on}</span>
            </div>
            <div class="cycle-meta">
                <span class="cycle-label">Left</span>
                <span class="cycle-meta-value success">{days_left} days</span>
            </div>
        </div>
        <div class="cycle-divider"></div>
        <div class="cycle-metric">
            <div class="cycle-label">Income</div>
            <div class="income-value">₹{income:,.0f}</div>
        </div>
        <div class="cycle-divider"></div>
        <div class="cycle-metric">
            <div class="cycle-label">Planned Commitments</div>
            <div class="reserved-value">₹{total_commitments:,.0f}</div>
        </div>
        <div class="cycle-divider"></div>
        <div class="cycle-metric">
            <div class="cycle-label">Remaining Commitments</div>
            <div class="pool-value">₹{remaining_commitments:,.0f}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

    st.markdown("<br>", unsafe_allow_html=True)

    if cycle_status == "PLANNED":
        st.warning(f"""**{selected_month}** hasn't started yet. This is a preview of your upcoming month. Editing will be enabled once the cycle becomes active.""")
    elif cycle_status == "CLOSED":
        st.warning(f"""**{selected_month}** has been successfully closed. This cycle is now locked and can no longer be edited.""")
    
    ##########################################################################
    # MONTHLY ACTIVITIES
    ##########################################################################

    with st.container(border=True):

        top_left = st.container()

        with top_left:

            st.markdown(f"""
            <div class="section-main-title">
                Monthly Activities ({selected_month})
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

        month_name = selected_date.strftime("%b")

        for activity in activities:

            if activity["type"] == "income":

                status_row = get_income_status(
                    activity["id"],
                    selected_date.month,
                    selected_date.year
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
                            selected_date.month,
                            selected_date.year,
                            amount,
                            "RECEIVED"
                        ),

                    cancel_callback=lambda i=activity["id"]:
                        save_income_status(
                            i,
                            selected_date.month,
                            selected_date.year,
                            0,
                            "CANCELLED"
                        ),
                )

            else:

                status_row = get_obligation_status(
                    activity["id"],
                    selected_date.month,
                    selected_date.year
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
                            selected_date.month,
                            selected_date.year,
                            amount,
                            "PAID"
                        ),

                    cancel_callback=lambda i=activity["id"]:
                        save_obligation_status(
                            i,
                            selected_date.month,
                            selected_date.year,
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
                Expected income sources every month.
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
                    step=100.0,
                    value=None
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

                if st.button(
                    "Cancel",
                    use_container_width=True
                ):

                    st.session_state.show_income_form = False

                    st.rerun()

                if st.button(
                    "💾 Save",
                    use_container_width=True
                ):

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

                    add_income_template(
                        vault_id,
                        name.strip(),
                        amount,
                        due_day,
                        account_map[selected_account]
                    )

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
                These create obligations every month.
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
                        step=100.0, value=None
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

                            add_commitment(
                                vault_id,
                                name.strip(),
                                amount,
                                due_day,
                                account_map[selected_account]
                            )

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
    # CLOSE MONTH
    ##########################################################################

    close_disabled = cycle_status != "ACTIVE"

    if st.button(
        "🔒 Close Month",
        use_container_width=True,
        disabled=close_disabled
    ):

        pending = []

        for activity in activities:

            if activity["type"] == "income":

                status_row = get_income_status(
                    activity["id"],
                    selected_date.month,
                    selected_date.year
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

                status_row = get_obligation_status(
                    activity["id"],
                    selected_date.month,
                    selected_date.year
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

        def handle_close_month(items):

            finalize_month(
                vault_id,
                selected_date.month,
                selected_date.year,
                items
            )
            next_month, next_year = get_next_month(
                selected_date.month,
                selected_date.year
            )

            st.session_state.month_selector = datetime(
                next_year,
                next_month,
                1
            ).strftime("%B %Y")

            st.success("Month closed successfully!")
            st.session_state.closing_month = False
            st.rerun()

        show_close_month_dialog(
            month_name=selected_month,
            pending_items=pending,
            on_confirm=handle_close_month
        )
