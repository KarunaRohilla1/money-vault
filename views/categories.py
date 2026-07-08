import streamlit as st

from db.categories import (
    add_category,
    delete_category,
    get_categories,
    update_category
)

ICONS = [
    ("\U0001f3f7\ufe0f", "Default"),
    ("🛒", "Groceries"),
    ("🍽️", "Eating Out"),
    ("🚕", "Transport"),
    ("🏠", "Home"),
    ("🎁", "Gifts"),
    ("✈️", "Travel"),
    ("📚", "Education"),
    ("💼", "Salary")
]

ICONS = [
    ("🏷️", "Default"),
    ("🛒", "Groceries"),
    ("🏡", "Home"),
    ("🍽", "Dining Out"),
    ("☕", "Coffee"),
    ("🛵", "Food Delivery"),
    ("⛽", "Fuel"),
    ("🚕", "Transport"),
    ("🏥", "Medical"),
    ("💪", "Fitness"),
    ("🛍", "Shopping"),
    ("🎬", "Entertainment"),
    ("📺", "Subscriptions"),
    ("✈️", "Travel"),
    ("📦", "Miscellaneous")
]


# ==================================================
# ADD CATEGORY
# ==================================================

@st.dialog("Add Category")
def add_category_dialog(vault_id):

    with st.form("add_category_form"):

        name = st.text_input(
            "Category Name"
        )

        category_type = st.selectbox(
            "Category Type",
            ["Expense", "Income"]
        )

        icon_lookup = {
            label: emoji
            for emoji, label in ICONS
        }

        icon_label = st.selectbox(
            "Icon",
            list(icon_lookup.keys())
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Add Category",
                use_container_width=True
            )

        with right:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

        if cancelled:
            st.rerun()

        if submitted:
            name = name.strip()
            if not name:
                st.error(
                    "Category name cannot be empty."
                )
            else:

                try:
                    add_category(
                        vault_id,
                        name,
                        icon_lookup[icon_label],
                        category_type
                    )
                except ValueError as error:
                    st.error(str(error))
                    st.stop()

                st.success(
                    "Category created"
                )

                st.rerun()


# ==================================================
# EDIT CATEGORY
# ==================================================

@st.dialog("Edit Category")
def edit_category_dialog(category):

    category_id = category[0]
    emoji = category[1]
    name = category[2]
    category_type = category[3]
    is_system = bool(category[5]) if len(category) > 5 else False

    if is_system:
        st.warning(
            "System categories cannot be edited."
        )
        if st.button(
            "Close",
            use_container_width=True
        ):
            st.rerun()
        return

    icon_lookup = {
        label: icon
        for icon, label in ICONS
    }

    reverse_lookup = {
        icon: label
        for icon, label in ICONS
    }

    with st.form(
        f"edit_category_{category_id}"
    ):

        new_name = st.text_input(
            "Category Name",
            value=name
        )

        new_type = st.selectbox(
            "Category Type",
            ["Expense", "Income"],
            index=(
                0
                if category_type == "Expense"
                else 1
            )
        )

        current_icon = reverse_lookup.get(
            emoji,
            "Groceries"
        )

        new_icon_label = st.selectbox(
            "Icon",
            list(icon_lookup.keys()),
            index=list(icon_lookup.keys()).index(
                current_icon
            )
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Save Changes",
                use_container_width=True
            )

        with right:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

        if cancelled:
            st.rerun()

        if submitted:
            new_name = new_name.strip()
            if not new_name:
                st.error(
                    "Category name cannot be empty."
                )
            else:
                try:
                    update_category(
                        category_id,
                        new_name,
                        icon_lookup[new_icon_label],
                        new_type
                    )
                except ValueError as error:
                    st.error(str(error))
                    st.stop()

                st.success(
                    "Category updated"
                )

                st.rerun()


# ==================================================
# DELETE CATEGORY
# ==================================================

@st.dialog("Delete Category")
def delete_category_dialog(category_id):

    st.warning(
        "Are you sure you want to archive this category?"
    )

    c1, c2 = st.columns(2)

    with c1:

        if st.button(
            "Delete Category",
            use_container_width=True
        ):

            try:
                delete_category(
                    category_id
                )
            except ValueError as error:
                st.error(str(error))
                st.stop()

            st.success(
                "Category deleted"
            )

            st.rerun()

    with c2:

        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.rerun()


# ==================================================
# MAIN PAGE
# ==================================================

def show_categories(vault_id):

    categories = get_categories(vault_id)

    # =====================================
    # HEADER
    # =====================================

    header_col, button_col = st.columns(
        [8, 2]
    )

    with header_col:

        st.markdown(
            """
            <div class="dashboard-header">
                <h2>🏷️ Categories</h2>
                <p>Manage your income and expense categories</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with button_col:

        st.write("")

        if st.button(
            "Add Category",
            use_container_width=True
        ):
            add_category_dialog(vault_id)

    # =====================================
    # FILTERS
    # =====================================

    all_count = len(categories)

    expense_count = len(
        [
            c
            for c in categories
            if c[3] == "Expense"
        ]
    )

    income_count = len(
        [
            c
            for c in categories
            if c[3] == "Income"
        ]
    )

    if "category_filter" not in st.session_state:
        st.session_state.category_filter = "All"

    left, right = st.columns(
        [6, 3]
    )

    with left:

        p1, p2, p3, spacer = st.columns(
        [1,1.5,1.5,5]
    )

        with p1:

            if st.button(
                f"All ({all_count})",
                key="cat_all"
            ):
                st.session_state.category_filter = "All"

        with p2:

            if st.button(
                f"Expense ({expense_count})",
                key="cat_expense"
            ):
                st.session_state.category_filter = "Expense"

        with p3:

            if st.button(
                f"Income ({income_count})",
                key="cat_income"
            ):
                st.session_state.category_filter = "Income"

    with right:

        search = st.text_input(
            "",
            placeholder="🔍 Search categories",
            label_visibility="collapsed"
        )

    filter_type = st.session_state.category_filter

    filtered = []

    for category in categories:

        name = category[2]
        category_type = category[3]

        if search:

            if search.lower() not in name.lower():
                continue

        if filter_type != "All":

            if category_type != filter_type:
                continue

        filtered.append(category)

    filtered.sort(
        key=lambda category: (
            bool(category[5]) if len(category) > 5 else False,
            (category[4] or "").lower() if len(category) > 4 else "",
            category[2].lower()
        )
    )

    st.divider()

    # =====================================
    # EMPTY STATE
    # =====================================

    if not filtered:

        st.info(
            "No categories found."
        )

        return

    # =====================================
    # CATEGORY CARDS
    # =====================================

    for category in filtered:

        category_id = category[0]
        icon = category[1]
        name = category[2]
        category_type = category[3]
        parent_category = category[4] if len(category) > 4 else None
        is_system = bool(category[5]) if len(category) > 5 else False

        c1, c2, c3, c4 = st.columns(
            [0.75, 5.25, 2, 1.5],
            vertical_alignment="center"
        )

        with c1:

            st.markdown(
                f"""
                <div class="mv-category-avatar">
                    {icon}
                </div>
                """,
                unsafe_allow_html=True
            )

        with c2:

            st.markdown(
                f"""
                <div class="mv-account-name">
                    {name}
                </div>
                <div class="mv-account-type">
                    {"System category" if is_system else "Custom category"}
                    {f" · {parent_category}" if parent_category else ""}
                </div>
                """,
                unsafe_allow_html=True
            )

        with c3:

            pill_class = (
                "mv-category-pill mv-category-income"
                if category_type == "Income"
                else
                "mv-category-pill mv-category-expense"
            )

            st.markdown(
                f"""
                <div class="mv-category-pill-wrapper">
                    <div class="{pill_class}">
                        {category_type}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with c4:

            if is_system:
                st.markdown(
                    """
                    <div class="mv-category-pill-wrapper">
                        <div class="mv-category-pill mv-category-income">
                            System
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                continue

            b1, b2 = st.columns(2)

            with b1:

                if st.button(
                    "✎",
                    key=f"edit_cat_{category_id}",
                    use_container_width=True
                ):
                    edit_category_dialog(
                        category
                    )

            with b2:

                if st.button(
                    "🗑",
                    key=f"delete_cat_{category_id}",
                    use_container_width=True
                ):
                    delete_category_dialog(
                        category_id
                    )
