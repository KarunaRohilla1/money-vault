from calendar import monthrange
from datetime import date
from html import escape

import streamlit as st

from db.categories import get_category_dropdown
from db.shared_bills import (
    BILL_CANCELLED,
    BILL_PAID,
    BILL_PENDING,
    BILL_SKIPPED,
    CYCLE_CLOSED,
    FREQUENCIES,
    add_shared_bill,
    cancel_shared_bill,
    close_cycle,
    duplicate_shared_bill,
    get_shared_bills,
    get_shared_bills_page_data,
    mark_bill_paid,
    skip_bill_instance,
    update_shared_bill
)
from db.vaults import get_shared_vault_participants
from views.dashboard import format_money


def format_month(month, year):
    return date(year, month, 1).strftime("%B %Y")


def format_due_label(value):
    due_date = date.fromisoformat(value)
    days = (due_date - date.today()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "In 1 day"
    if days > 1:
        return f"In {days} days"
    return f"{abs(days)} days overdue"


def category_options(shared_vault_id):
    categories = get_category_dropdown(
        shared_vault_id
    )
    labels = [
        f"{row[1]} {row[2]}"
        for row in categories
    ]
    mapping = {
        f"{row[1]} {row[2]}": row[0]
        for row in categories
    }
    return labels, mapping


def bill_form_fields(shared_vault_id, defaults=None, key_prefix="bill"):
    defaults = defaults or {}
    labels, mapping = category_options(
        shared_vault_id
    )
    category_id = defaults.get("category_id")
    category_index = 0
    for index, label in enumerate(labels):
        if mapping[label] == category_id:
            category_index = index
            break

    name = st.text_input(
        "Bill Name",
        value=defaults.get("name", ""),
        key=f"{key_prefix}_name"
    )
    category_label = st.selectbox(
        "Category",
        labels,
        index=category_index,
        key=f"{key_prefix}_category"
    )
    amount = st.number_input(
        "Amount",
        min_value=0.0,
        value=(
            float(defaults["amount"])
            if defaults.get("amount") is not None
            else None
        ),
        step=0.01,
        placeholder="Enter Amount",
        format="%.2f",
        key=f"{key_prefix}_amount"
    )
    frequency = st.selectbox(
        "Frequency",
        FREQUENCIES,
        index=FREQUENCIES.index(defaults.get("frequency", "Monthly"))
        if defaults.get("frequency", "Monthly") in FREQUENCIES
        else 0,
        key=f"{key_prefix}_frequency"
    )
    due_day = st.number_input(
        "Due Day",
        min_value=1,
        max_value=31,
        value=int(defaults.get("due_day", 1) or 1),
        step=1,
        key=f"{key_prefix}_due_day"
    )
    start_date = st.date_input(
        "Start Date",
        value=date.fromisoformat(
            defaults.get("start_date")
            or date.today().replace(day=1).isoformat()
        ),
        key=f"{key_prefix}_start_date"
    )
    end_date_enabled = st.checkbox(
        "Set End Date",
        value=bool(defaults.get("end_date")),
        key=f"{key_prefix}_end_date_enabled"
    )
    end_date = None
    if end_date_enabled:
        end_date = st.date_input(
            "End Date",
            value=date.fromisoformat(
                defaults.get("end_date")
                or date.today().isoformat()
            ),
            key=f"{key_prefix}_end_date"
        )
    notes = st.text_area(
        "Notes",
        value=defaults.get("notes", ""),
        key=f"{key_prefix}_notes"
    )
    is_active = st.checkbox(
        "Active",
        value=bool(defaults.get("is_active", 1)),
        key=f"{key_prefix}_active"
    )

    return {
        "name": name,
        "category_id": mapping[category_label],
        "amount": amount,
        "frequency": frequency,
        "due_day": due_day,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat() if end_date else None,
        "notes": notes,
        "is_active": is_active
    }


@st.dialog("Add Shared Bill")
def add_bill_dialog(shared_vault_id):
    values = bill_form_fields(
        shared_vault_id,
        key_prefix="add_shared_bill"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Add Bill",
            use_container_width=True,
            key="confirm_add_shared_bill"
        ):
            try:
                add_shared_bill(
                    shared_vault_id,
                    **values
                )
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    with col2:
        if st.button(
            "Cancel",
            use_container_width=True,
            key="cancel_add_shared_bill"
        ):
            st.rerun()


@st.dialog("Edit Shared Bill")
def edit_bill_dialog(shared_vault_id, bill):
    values = bill_form_fields(
        shared_vault_id,
        defaults=bill,
        key_prefix=f"edit_shared_bill_{bill['id']}"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Save Changes",
            use_container_width=True,
            key=f"save_shared_bill_{bill['id']}"
        ):
            try:
                update_shared_bill(
                    bill["id"],
                    **values
                )
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    with col2:
        if st.button(
            "Cancel",
            use_container_width=True,
            key=f"cancel_edit_shared_bill_{bill['id']}"
        ):
            st.rerun()


@st.dialog("Mark Bill Paid")
def mark_paid_dialog(instance, participants):
    payer_map = {
        participant[1]: participant[0]
        for participant in participants
    }
    payer_name = st.selectbox(
        "Who paid?",
        list(payer_map.keys()),
        key=f"payer_{instance['id']}"
    )
    payment_date = st.date_input(
        "Payment Date",
        value=date.today(),
        key=f"payment_date_{instance['id']}"
    )
    notes = st.text_area(
        "Notes",
        key=f"payment_notes_{instance['id']}"
    )
    st.caption(
        f"Amount: {format_money(instance['amount'])}"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Confirm Payment",
            use_container_width=True,
            key=f"confirm_paid_{instance['id']}"
        ):
            try:
                mark_bill_paid(
                    instance["id"],
                    payer_map[payer_name],
                    payment_date.isoformat(),
                    notes
                )
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    with col2:
        if st.button(
            "Cancel",
            use_container_width=True,
            key=f"cancel_paid_{instance['id']}"
        ):
            st.rerun()


@st.dialog("Close Household Cycle")
def close_cycle_dialog(data):
    summary = data["summary"]
    st.warning(
        "Closing this cycle marks the current household cycle as closed."
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Bills", format_money(summary["total_amount"]))
    col2.metric("Paid", format_money(summary["paid_amount"]))
    col3.metric("Pending", summary["pending_count"])

    for participant in data["participants"]:
        st.write(
            f"{participant['name']}: Expected {format_money(participant['expected'])}, "
            f"Paid {format_money(participant['paid'])}, "
            f"Difference {format_money(participant['difference'])}"
        )

    if summary["balance"]:
        for settlement in summary["balance"]:
            st.info(
                f"{settlement['from']} owes {settlement['to']} {format_money(settlement['amount'])}."
            )
    else:
        st.info("No settlement needed.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Close Cycle",
            use_container_width=True,
            key="confirm_close_shared_bill_cycle"
        ):
            close_cycle(
                data["cycle"]["id"]
            )
            st.rerun()
    with col2:
        if st.button(
            "Cancel",
            use_container_width=True,
            key="cancel_close_shared_bill_cycle"
        ):
            st.rerun()


def bill_definition_map(shared_vault_id):
    definitions = {}
    for row in get_shared_bills(shared_vault_id):
        definitions[row[0]] = {
            "id": row[0],
            "name": row[1],
            "amount": row[2],
            "due_day": row[3],
            "category_id": row[4],
            "notes": row[7],
            "frequency": row[8],
            "start_date": row[9],
            "end_date": row[10],
            "is_active": row[11]
        }
    return definitions


def summary_cards(data):
    summary = data["summary"]
    next_due = summary["next_due"]
    next_due_name = next_due["name"] if next_due else "None"
    next_due_date = (
        date.fromisoformat(next_due["due_date"]).strftime("%d %b")
        if next_due
        else "-"
    )
    return (
        '<div class="mv-shared-stats mv-bills-stats">'
        f'<div class="mv-shared-stat purple"><div class="mv-shared-stat-icon material-symbols-outlined">business_center</div><div class="mv-shared-stat-copy"><div class="mv-shared-stat-title">Total Bills</div><div class="mv-shared-stat-value">{format_money(summary["total_amount"])}</div><div class="mv-shared-stat-subtitle">Across {summary["total_count"]} bills</div></div></div>'
        f'<div class="mv-shared-stat green"><div class="mv-shared-stat-icon material-symbols-outlined">check_circle</div><div class="mv-shared-stat-copy"><div class="mv-shared-stat-title">Paid</div><div class="mv-shared-stat-value">{format_money(summary["paid_amount"])}</div><div class="mv-shared-stat-subtitle">{summary["paid_count"]} bills paid</div></div></div>'
        f'<div class="mv-shared-stat orange"><div class="mv-shared-stat-icon material-symbols-outlined">schedule</div><div class="mv-shared-stat-copy"><div class="mv-shared-stat-title">Remaining</div><div class="mv-shared-stat-value">{format_money(summary["remaining_amount"])}</div><div class="mv-shared-stat-subtitle">{summary["pending_count"]} pending</div></div></div>'
        f'<div class="mv-shared-stat blue"><div class="mv-shared-stat-icon material-symbols-outlined">calendar_month</div><div class="mv-shared-stat-copy"><div class="mv-shared-stat-title">Next Due</div><div class="mv-shared-stat-value">{escape(next_due_date)}</div><div class="mv-shared-stat-subtitle">{escape(next_due_name)}</div></div></div>'
        '</div>'
    )


def contribution_section(data):
    cards = []
    for participant in data["participants"]:
        difference_class = (
            "positive"
            if participant["difference"] >= 0
            else "negative"
        )
        cards.append(
            '<div class="mv-bill-contribution-person">'
            f'<div class="mv-bill-person-name">{escape(participant["name"])}</div>'
            '<div class="mv-bill-contribution-grid">'
            f'<div><span>Expected</span><strong>{format_money(participant["expected"])}</strong></div>'
            f'<div><span>Paid</span><strong>{format_money(participant["paid"])}</strong></div>'
            f'<div><span>Difference</span><strong class="{difference_class}">{format_money(participant["difference"])}</strong></div>'
            '</div>'
            '<div class="mv-bill-progress"><div style="width:'
            f'{min(participant["progress"], 120):.0f}%"></div></div>'
            f'<div class="mv-bill-progress-label">{participant["progress"]:.0f}% of expected</div>'
            '</div>'
        )
    participant_cards = "".join(cards)
    if data["summary"]["balance"]:
        balance_text = " ".join(
            f'{item["from"]} owes {item["to"]} {format_money(item["amount"])}.'
            for item in data["summary"]["balance"]
        )
    else:
        balance_text = "All participants are settled for this cycle."

    return (
        '<section class="mv-shared-panel mv-bill-contribution-panel">'
        '<div class="mv-shared-panel-head">'
        '<div class="mv-shared-panel-title">Household Contribution This Cycle</div>'
        '</div>'
        f'<div class="mv-bill-contribution-list">{participant_cards}</div>'
        f'<div class="mv-bill-balance-note">{escape(balance_text)}</div>'
        '</section>'
    )


def pending_bill_row(bill, read_only):
    shares = "".join(
        (
            '<div>'
            f'<span>{escape(share["participant_name"][:1])}</span> '
            f'{format_money(share["expected_amount"])} ({share["expected_percentage"]:.2f}%)'
            '</div>'
        )
        for share in bill["shares"]
    )
    due_date = date.fromisoformat(
        bill["due_date"]
    ).strftime("%d %b %Y")
    status_class = bill["status"].lower()
    return (
        '<div class="mv-bill-row">'
        '<div class="mv-bill-name">'
        f'<div class="mv-bill-icon material-symbols-outlined">{escape(str(bill["icon"]))}</div>'
        '<div>'
        f'<strong>{escape(bill["name"])}</strong>'
        f'<span>{escape(bill["frequency"])}</span>'
        '</div>'
        '</div>'
        f'<div>{format_money(bill["amount"])}</div>'
        f'<div><strong>{due_date}</strong><span>{format_due_label(bill["due_date"])}</span></div>'
        f'<div class="mv-bill-shares">{shares}</div>'
        f'<div><span class="mv-bill-status {status_class}">{escape(bill["status"])}</span></div>'
        '<div></div>'
        '</div>'
    )


def completed_bill_row(bill):
    paid_date = (
        date.fromisoformat(bill["payment_date"]).strftime("%d %b %Y")
        if bill["payment_date"]
        else "-"
    )
    return (
        '<div class="mv-bill-row completed">'
        '<div class="mv-bill-name">'
        f'<div class="mv-bill-icon material-symbols-outlined">{escape(str(bill["icon"]))}</div>'
        '<div>'
        f'<strong>{escape(bill["name"])}</strong>'
        f'<span>{escape(bill["frequency"])}</span>'
        '</div>'
        '</div>'
        f'<div>{format_money(bill["amount"])}</div>'
        f'<div>Paid on<br><strong>{paid_date}</strong></div>'
        f'<div>Paid by<br><strong>{escape(bill["payer_name"] or "-")}</strong></div>'
        '<div><span class="mv-bill-status paid">Paid</span></div>'
        '<div></div>'
        '</div>'
    )


def render_pending_bills(shared_vault_id, data, read_only):
    definitions = bill_definition_map(
        shared_vault_id
    )
    st.markdown(
        '<section class="mv-shared-panel mv-bill-table-panel"><div class="mv-shared-panel-head"><div class="mv-shared-panel-title">Upcoming & Pending Bills</div></div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="mv-bill-table-head"><div>Bill</div><div>Amount</div><div>Due Date</div><div>Expected Contribution</div><div>Status</div><div>Action</div></div>',
        unsafe_allow_html=True
    )
    participants = get_shared_vault_participants(
        shared_vault_id
    )
    for bill in data["pending_bills"]:
        row_col, action_col = st.columns(
            [7, 1.4],
            vertical_alignment="center"
        )
        with row_col:
            st.markdown(
                pending_bill_row(
                    bill,
                    read_only
                ),
                unsafe_allow_html=True
            )
        with action_col:
            if bill["status"] == BILL_PENDING and not read_only:
                if st.button(
                    "Mark Paid",
                    key=f"mark_paid_{bill['id']}",
                    use_container_width=True
                ):
                    mark_paid_dialog(
                        bill,
                        participants
                    )
            if not read_only and hasattr(st, "popover"):
                with st.popover("⋮"):
                    definition = definitions.get(
                        bill["bill_id"]
                    )
                    if definition and st.button(
                        "Edit",
                        key=f"edit_bill_{bill['id']}",
                        use_container_width=True
                    ):
                        edit_bill_dialog(
                            shared_vault_id,
                            definition
                        )
                    if st.button(
                        "Duplicate",
                        key=f"duplicate_bill_{bill['id']}",
                        use_container_width=True
                    ):
                        duplicate_shared_bill(
                            bill["bill_id"]
                        )
                        st.rerun()
                    if bill["status"] == BILL_PENDING and st.button(
                        "Skip",
                        key=f"skip_bill_{bill['id']}",
                        use_container_width=True
                    ):
                        skip_bill_instance(
                            bill["id"]
                        )
                        st.rerun()
                    if definition and st.button(
                        "Cancel",
                        key=f"cancel_bill_{bill['id']}",
                        use_container_width=True
                    ):
                        cancel_shared_bill(
                            bill["bill_id"]
                        )
                        st.rerun()
                    if definition and st.button(
                        "Delete",
                        key=f"delete_bill_{bill['id']}",
                        use_container_width=True
                    ):
                        cancel_shared_bill(
                            bill["bill_id"]
                        )
                        st.rerun()

    if not data["pending_bills"]:
        st.info("No upcoming bills for this cycle.")
    if not read_only and st.button(
        "Add New Bill",
        use_container_width=True,
        key="add_new_shared_bill"
    ):
        add_bill_dialog(
            shared_vault_id
        )
    st.markdown(
        '</section>',
        unsafe_allow_html=True
    )


def render_completed_bills(data):
    with st.expander(
        "Completed Bills",
        expanded=False
    ):
        if not data["completed_bills"]:
            st.info("No completed bills for this cycle.")
            return
        for bill in data["completed_bills"]:
            st.markdown(
                completed_bill_row(bill),
                unsafe_allow_html=True
            )


def show_shared_bills(shared_vault_id):
    data = get_shared_bills_page_data(
        shared_vault_id
    )
    cycle = data["cycle"]
    read_only = False

    header_col, cycle_col, status_col, close_col = st.columns(
        [1.8, 0.8, 0.7, 0.7],
        vertical_alignment="center"
    )
    with header_col:
        st.markdown(
            """
            <div class="dashboard-header">
                <h2>Bills</h2>
                <p>Track, manage and pay your household bills.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    with cycle_col:
        st.selectbox(
            "Cycle",
            [format_month(cycle["month"], cycle["year"])],
            label_visibility="collapsed"
        )
    with status_col:
        st.success(
            f"{cycle['status']} Cycle"
        )
    with close_col:
        if st.button(
            "Close Cycle",
            use_container_width=True,
            disabled=read_only,
            key="close_shared_bill_cycle"
        ):
            close_cycle_dialog(
                data
            )

    start = date.fromisoformat(cycle["start_date"])
    end = date.fromisoformat(cycle["end_date"])
    st.markdown(
        f"""
            <div class="mv-cycle-banner">
                <strong>Your current household cycle</strong>
            <span>{start.strftime('%d %b %Y')} - {end.strftime('%d %b %Y')}</span>
                <em>Closing the cycle will lock bill status and contribution calculations.</em>
            </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        summary_cards(data),
        unsafe_allow_html=True
    )
    st.markdown(
        contribution_section(data),
        unsafe_allow_html=True
    )
    render_pending_bills(
        shared_vault_id,
        data,
        read_only
    )
    render_completed_bills(
        data
    )
    st.info(
        "Tip: Bills are based on participant income ratio from Planning. Future income changes affect future cycles."
    )
