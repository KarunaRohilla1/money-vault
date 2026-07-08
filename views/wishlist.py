import pandas as pd
import streamlit as st

from db.wishlist import (
    add_wishlist_category,
    add_wishlist_item,
    delete_wishlist_category,
    delete_wishlist_item,
    get_wishlist_categories,
    get_wishlist_category,
    get_wishlist_category_item_count,
    get_wishlist_item,
    get_wishlist_items,
    get_wishlist_summary,
    update_wishlist_category,
    update_wishlist_item
)


DEFAULT_CATEGORY = "General"


def format_money(amount):
    return f"\u20b9{amount:,.0f}"


def item_image(image_url, name):
    if image_url:
        return (
            f'<img class="mv-wishlist-thumb" src="{image_url}" '
            f'alt="{name}">'
        )

    initials = "".join(
        word[0]
        for word in name.split()[:2]
    ).upper() or "W"

    return f'<div class="mv-wishlist-thumb-fallback">{initials}</div>'


def category_names(vault_id):
    names = [
        category[2]
        for category in get_wishlist_categories(vault_id)
    ]

    return names or [DEFAULT_CATEGORY]


@st.dialog("Add Wishlist Category")
def add_wishlist_category_dialog(vault_id):

    with st.form("add_wishlist_category_form"):
        name = st.text_input(
            "Category Name"
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Save Category",
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
            if not name.strip():
                st.error("Category name is required.")
                st.stop()

            add_wishlist_category(
                vault_id,
                name.strip()
            )

            st.rerun()


@st.dialog("Edit Wishlist Category")
def edit_wishlist_category_dialog(category_id):

    category = get_wishlist_category(category_id)

    if not category:
        st.error("Wishlist category not found.")
        return

    with st.form(f"edit_wishlist_category_{category_id}"):
        name = st.text_input(
            "Category Name",
            value=category[2]
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
            try:
                update_wishlist_category(
                    category_id,
                    category[1],
                    category[2],
                    name
                )
            except ValueError as error:
                st.error(str(error))
                st.stop()

            st.rerun()


@st.dialog("Delete Wishlist Category")
def delete_wishlist_category_dialog(category_id):

    category = get_wishlist_category(category_id)

    if not category:
        st.error("Wishlist category not found.")
        return

    item_count = get_wishlist_category_item_count(
        category[1],
        category[2]
    )

    if item_count:
        st.warning(
            f"Delete '{category[2]}'? {item_count} wishlist item(s) will move to General."
        )
    else:
        st.warning(
            f"Delete '{category[2]}'?"
        )

    left, right = st.columns(2)

    with left:
        if st.button(
            "Delete",
            use_container_width=True
        ):
            delete_wishlist_category(
                category_id,
                category[1],
                category[2],
                fallback=DEFAULT_CATEGORY
            )
            st.rerun()

    with right:
        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.session_state.delete_wishlist_category_id = None
            st.rerun()


@st.dialog("Wishlist Categories")
def view_wishlist_categories_dialog(vault_id):

    categories = get_wishlist_categories(vault_id)

    if not categories:
        st.info("No wishlist categories yet.")
        return

    for category in categories:
        row = st.columns(
            [5, 1],
            vertical_alignment="center"
        )

        with row[0]:
            st.markdown(
                f"""
                <div class="mv-wishlist-category-row">
                    <span class="material-symbols-outlined">label</span>
                    <strong>{category[2]}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )

        with row[1]:
            if hasattr(st, "popover"):
                with st.popover("⋮"):
                    if st.button(
                        "Edit",
                        key=f"edit_wishlist_category_{category[0]}",
                        use_container_width=True
                    ):
                        st.session_state.edit_wishlist_category_id = category[0]
                        st.rerun()

                    if st.button(
                        "Delete",
                        key=f"delete_wishlist_category_{category[0]}",
                        use_container_width=True
                    ):
                        st.session_state.delete_wishlist_category_id = category[0]
                        st.rerun()
            elif st.button(
                "Edit",
                key=f"edit_wishlist_category_{category[0]}"
            ):
                st.session_state.edit_wishlist_category_id = category[0]
                st.rerun()

    if st.button(
        "Close",
        use_container_width=True
    ):
        st.rerun()


@st.dialog("Add Wishlist Item")
def add_wishlist_dialog(vault_id):

    categories = category_names(vault_id)

    with st.form("add_wishlist_item_form"):

        name = st.text_input("Item Name")
        category = st.selectbox(
            "Category",
            categories
        )

        cost = st.number_input(
            "Cost",
            min_value=0.0,
            step=0.01,
            value=None,
            placeholder="Enter Amount",
            format="%.2f"
        )

        image_url = st.text_input(
            "Image URL",
            placeholder="Optional"
        )
        notes = st.text_area("Notes")

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Save Item",
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
            if not name.strip():
                st.error("Item name is required.")
                st.stop()

            if cost is None or cost <= 0:
                st.error("Cost must be greater than 0.")
                st.stop()

            add_wishlist_item(
                vault_id,
                name.strip(),
                category,
                cost,
                image_url=image_url.strip(),
                notes=notes.strip()
            )

            st.rerun()


@st.dialog("Edit Wishlist Item")
def edit_wishlist_dialog(item_id, vault_id):

    item = get_wishlist_item(item_id)

    if not item:
        st.error("Wishlist item not found.")
        return

    categories = category_names(vault_id)
    if item[3] and item[3] not in categories:
        categories = [item[3]] + categories

    current_category = (
        item[3]
        if item[3] in categories
        else categories[0]
    )

    with st.form(f"edit_wishlist_item_{item_id}"):

        name = st.text_input(
            "Item Name",
            value=item[2]
        )
        category = st.selectbox(
            "Category",
            categories,
            index=categories.index(current_category)
        )

        cost = st.number_input(
            "Cost",
            min_value=0.0,
            step=0.01,
            value=float(item[4]),
            placeholder="Enter Amount",
            format="%.2f"
        )

        image_url = st.text_input(
            "Image URL",
            value=item[8] or ""
        )
        notes = st.text_area(
            "Notes",
            value=item[9] or ""
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
            if not name.strip():
                st.error("Item name is required.")
                st.stop()

            if cost <= 0:
                st.error("Cost must be greater than 0.")
                st.stop()

            update_wishlist_item(
                item_id,
                name.strip(),
                category,
                cost,
                item[5],
                image_url=image_url.strip(),
                notes=notes.strip()
            )

            st.rerun()


@st.dialog("Delete Wishlist Item")
def delete_wishlist_dialog(item_id):

    st.warning("Delete this wishlist item?")

    left, right = st.columns(2)

    with left:
        if st.button(
            "Delete",
            use_container_width=True
        ):
            delete_wishlist_item(item_id)
            st.rerun()

    with right:
        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.rerun()


def render_summary(summary):

    cols = st.columns(2)

    cards = [
        (
            "shopping_bag",
            "Total Items",
            str(summary["total_items"]),
            "items in wishlist",
            "purple"
        ),
        (
            "account_balance_wallet",
            "Total Cost",
            format_money(summary["total_cost"]),
            "across all items",
            "green"
        )
    ]

    for col, card in zip(cols, cards):
        icon, title, value, caption, tone = card

        with col:
            st.markdown(
                f"""
                <div class="mv-wishlist-summary">
                    <div class="mv-wishlist-summary-icon {tone} material-symbols-outlined">{icon}</div>
                    <div>
                        <div class="mv-wishlist-summary-title">{title}</div>
                        <div class="mv-wishlist-summary-value {tone}">{value}</div>
                        <div class="mv-wishlist-summary-caption">{caption}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )


def render_wishlist_table(items):

    st.markdown(
        """
        <div class="mv-wishlist-table-head">
            <div>Item</div>
            <div>Cost</div>
            <div>Actions</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    for item in items:
        item_id = item[0]
        name = item[1]
        category = item[2]
        cost = item[3]
        image_url = item[8]

        row_col, edit_col, delete_col = st.columns(
            [7.7, 0.55, 0.55],
            vertical_alignment="center"
        )

        with row_col:
            st.markdown(
                f"""
                <div class="mv-wishlist-row">
                    <div class="mv-wishlist-item-cell">
                        {item_image(image_url, name)}
                        <div>
                            <div class="mv-wishlist-item-name">{name}</div>
                            <div class="mv-wishlist-item-category">{category}</div>
                        </div>
                    </div>
                    <div class="mv-wishlist-money">{format_money(cost)}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with edit_col:
            if st.button(
                "edit",
                key=f"edit_wishlist_{item_id}",
                use_container_width=True,
                help="Edit item"
            ):
                edit_wishlist_dialog(item_id, st.session_state.vault_id)

        with delete_col:
            if st.button(
                "delete",
                key=f"delete_wishlist_{item_id}",
                use_container_width=True,
                help="Delete item"
            ):
                delete_wishlist_dialog(item_id)


def show_wishlist(vault_id):

    if st.session_state.get("edit_wishlist_category_id"):
        category_id = st.session_state.pop("edit_wishlist_category_id")
        edit_wishlist_category_dialog(category_id)

    if st.session_state.get("delete_wishlist_category_id"):
        category_id = st.session_state.pop("delete_wishlist_category_id")
        delete_wishlist_category_dialog(category_id)

    header_left, view_categories_button, category_button, item_button = st.columns(
        [3.5, 1, 1, 1],
        vertical_alignment="center"
    )

    with header_left:
        st.markdown(
            """
            <div class="mv-wishlist-title">
                <span class="material-symbols-outlined">favorite</span>
                <div>
                    <h2>Wishlist</h2>
                    <p>Track the things you want and plan to make them yours.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with view_categories_button:
        if st.button(
            "View Categories",
            use_container_width=True
        ):
            view_wishlist_categories_dialog(vault_id)

    with category_button:
        if st.button(
            "Add Category",
            use_container_width=True
        ):
            add_wishlist_category_dialog(vault_id)

    with item_button:
        if st.button(
            "Add Item",
            use_container_width=True
        ):
            add_wishlist_dialog(vault_id)

    summary = get_wishlist_summary(vault_id)
    render_summary(summary)

    st.markdown("<br>", unsafe_allow_html=True)

    categories = category_names(vault_id)

    filter_cols = st.columns(
        [2.6, 1.7, 0.9],
        vertical_alignment="center"
    )

    with filter_cols[0]:
        search = st.text_input(
            "Search",
            placeholder="Search wishlist items...",
            label_visibility="collapsed"
        )

    with filter_cols[1]:
        category_filter = st.selectbox(
            "Category",
            ["All Categories"] + categories,
            label_visibility="collapsed"
        )

    items = get_wishlist_items(
        vault_id,
        search=search,
        category=category_filter
    )

    with filter_cols[2]:
        if items:
            export = pd.DataFrame(
                [
                    (
                        item[0],
                        item[1],
                        item[2],
                        item[3],
                        item[8],
                        item[9]
                    )
                    for item in items
                ],
                columns=[
                    "ID",
                    "Name",
                    "Category",
                    "Cost",
                    "Image URL",
                    "Notes"
                ]
            )

            st.download_button(
                "Export",
                export.to_csv(index=False).encode("utf-8-sig"),
                "wishlist.csv",
                "text/csv",
                use_container_width=True
            )
        else:
            st.button(
                "Export",
                disabled=True,
                use_container_width=True
            )

    if not items:
        st.info("No wishlist items found.")
    else:
        render_wishlist_table(items)

    st.markdown(
        """
        <div class="mv-wishlist-footer">
            <span class="material-symbols-outlined">info</span>
            <div>
                <strong>Add items you wish to buy and organize them by category.</strong>
                <p>Stay focused on what matters next.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
