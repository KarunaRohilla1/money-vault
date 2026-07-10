import os
import time

import streamlit as st

from db.schema import (
    initialize_database,
    migrate_database
)
from db.core import setup_application_data
from db.vaults import (
    get_connected_shared_vaults,
    get_vault_by_id,
    get_vaults,
    vault_exists,
    verify_pin
)
from db.cache import clear_data_cache


PROFILED_PAGES = {
    "Dashboard",
    "Accounts",
    "Transactions",
    "Planning",
    "Reports",
    "Shared Expenses",
    "Bills"
}

PERSONAL_MENU_ITEMS = [
    "Dashboard",
    "Accounts",
    "Planning",
    "Transactions",
    "Transfers",
    "Reports",
    "Categories",
    "Wishlist",
    "Settings"
]

SHARED_MENU_ITEMS = [
    "Dashboard",
    "Shared Expenses",
    "Bills"
]

@st.cache_data(show_spinner=False)
def get_css():
    with open(
        "styles/main.css", encoding="utf-8"
    ) as f:
        return f.read()


def load_css():
    st.markdown(
        f"<style>{get_css()}</style>",
        unsafe_allow_html=True
    )


@st.cache_resource(show_spinner=False)
def bootstrap_database():
    initialize_database()

    if os.environ.get("MONEY_VAULT_RUN_RUNTIME_MIGRATIONS") == "1":
        migrate_database()

    setup_application_data()
    return True


def render_profiled_page(page_name, render_function, *args):
    start = time.perf_counter()

    try:
        return render_function(*args)

    finally:
        elapsed = time.perf_counter() - start

        if page_name in PROFILED_PAGES:
            print(f"[money-vault perf] {page_name}: {elapsed:.3f}s")


def get_navigation_items(vault_type):
    if vault_type == "Shared":
        return SHARED_MENU_ITEMS

    return PERSONAL_MENU_ITEMS


def clear_authentication_state():
    for key in [
        "authenticated",
        "vault_id",
        "vault_name",
        "is_admin",
        "active_vault_id",
        "active_vault_name",
        "original_personal_vault_id",
        "original_personal_vault_name",
        "original_personal_is_admin",
        "pending_shared_vault_id",
        "pending_shared_vault_name",
        "shared_global_page"
    ]:
        if key in st.session_state:
            del st.session_state[key]

    clear_data_cache()


def activate_vault(vault_id, vault_name, is_admin):
    st.session_state.vault_id = vault_id
    st.session_state.vault_name = vault_name
    st.session_state.active_vault_id = vault_id
    st.session_state.active_vault_name = vault_name
    st.session_state.is_admin = bool(is_admin)


def render_vault_switcher(current_vault, vault_type):
    active_name = st.session_state.vault_name

    with st.sidebar.expander(
        f"{active_name} ▼",
        expanded=False
    ):
        if vault_type == "Shared":
            st.markdown(f"🏠 **{active_name}**")

            original_id = st.session_state.get(
                "original_personal_vault_id"
            )
            original_name = st.session_state.get(
                "original_personal_vault_name"
            )

            if original_id and original_name:
                if st.button(
                    f"👤 Return to {original_name}",
                    use_container_width=True
                ):
                    activate_vault(
                        original_id,
                        original_name,
                        st.session_state.get(
                            "original_personal_is_admin",
                            False
                        )
                    )
                    st.rerun()

        else:
            st.markdown(f"✓ **{active_name}**")

            personal_id = st.session_state.get(
                "original_personal_vault_id",
                st.session_state.vault_id
            )
            shared_vaults = get_connected_shared_vaults(
                personal_id
            )

            for shared_vault in shared_vaults:
                shared_id = shared_vault[0]
                shared_name = shared_vault[1]

                if st.button(
                    f"🏠 Switch to {shared_name}",
                    use_container_width=True,
                    key=f"switch_shared_{shared_id}"
                ):
                    st.session_state.pending_shared_vault_id = shared_id
                    st.session_state.pending_shared_vault_name = shared_name

            pending_id = st.session_state.get(
                "pending_shared_vault_id"
            )
            pending_name = st.session_state.get(
                "pending_shared_vault_name"
            )

            if pending_id and pending_name:
                pin = st.text_input(
                    f"{pending_name} PIN",
                    type="password",
                    key="shared_switch_pin"
                )

                if st.button(
                    "Unlock Shared",
                    use_container_width=True
                ):
                    shared_vault = verify_pin(
                        pending_name,
                        pin
                    )

                    if shared_vault and int(shared_vault[0]) == int(pending_id):
                        activate_vault(
                            shared_vault[0],
                            shared_vault[1],
                            shared_vault[3]
                        )
                        st.session_state.pending_shared_vault_id = None
                        st.session_state.pending_shared_vault_name = None
                        st.rerun()

                    else:
                        st.error("Incorrect Shared vault PIN.")

        if st.button(
            "Logout",
            use_container_width=True
        ):
            clear_authentication_state()
            st.rerun()


def render_sidebar_navigation(vault_type):
    menu_items = get_navigation_items(vault_type)

    page = st.sidebar.radio(
        "Navigation",
        menu_items,
        key=f"navigation_{vault_type}"
    )

    if vault_type == "Shared":
        previous_page = st.session_state.get(
            "shared_navigation_previous"
        )
        if previous_page != page:
            st.session_state.shared_global_page = None
            st.session_state.shared_navigation_previous = page

        st.sidebar.divider()
        if st.sidebar.button(
            "Settings",
            use_container_width=True,
            key="global_settings_button"
        ):
            st.session_state.shared_global_page = "Settings"

        if st.session_state.get("shared_global_page"):
            page = st.session_state.shared_global_page

    return page


st.set_page_config(
    page_title="Money Vault",
    page_icon="💰",
    layout="wide"
)

load_css()

bootstrap_database()

# -------------------
# Session State
# -------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "vault_id" not in st.session_state:
    st.session_state.vault_id = None

if "vault_name" not in st.session_state:
    st.session_state.vault_name = None

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "active_vault_id" not in st.session_state:
    st.session_state.active_vault_id = st.session_state.vault_id

if "active_vault_name" not in st.session_state:
    st.session_state.active_vault_name = st.session_state.vault_name

if "original_personal_vault_id" not in st.session_state:
    st.session_state.original_personal_vault_id = None

if "original_personal_vault_name" not in st.session_state:
    st.session_state.original_personal_vault_name = None

if "original_personal_is_admin" not in st.session_state:
    st.session_state.original_personal_is_admin = False


# -------------------
# Login Screen
# -------------------

if not st.session_state.authenticated:

    st.title("💰 Money Vault")

    if not vault_exists():
        st.error("No vaults configured.")
        st.stop()

    vaults = get_vaults()

    selected_vault = st.selectbox(
        "Select Vault",
        [vault[1] for vault in vaults]
    )

    pin = st.text_input(
        "PIN",
        type="password"
    )

    if st.button("Unlock"):

        vault = verify_pin(
            selected_vault,
            pin
        )

        if vault:

            st.session_state.authenticated = True
            activate_vault(
                vault[0],
                vault[1],
                vault[3]
            )

            vault_details = get_vault_by_id(
                vault[0]
            )
            logged_in_vault_type = (
                vault_details[4]
                if vault_details and len(vault_details) > 4
                else "Individual"
            )

            if logged_in_vault_type == "Individual":
                st.session_state.original_personal_vault_id = vault[0]
                st.session_state.original_personal_vault_name = vault[1]
                st.session_state.original_personal_is_admin = bool(vault[3])

            st.rerun()

        else:
            st.error("Incorrect PIN")


# -------------------
# Logged In Area
# -------------------

else:
    current_vault = get_vault_by_id(
        st.session_state.vault_id
    )
    vault_type = (
        current_vault[4]
        if current_vault and len(current_vault) > 4
        else "Individual"
    )

    st.sidebar.markdown(
    f"""
    <div class="vault-card">
        <div class="vault-name">
            🔓 {st.session_state.vault_name}
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

    render_vault_switcher(
        current_vault,
        vault_type
    )

    page = render_sidebar_navigation(
        vault_type
    )

    previous_page = st.session_state.get("current_page")
    if page != previous_page:
        if page == "Planning":
            st.session_state.pop(
                "planning_selected_cycle_start",
                None
            )
        st.session_state.current_page = page

    if page == "Dashboard":
        from views.dashboard import show_dashboard

        render_profiled_page(
            page,
            show_dashboard,
            st.session_state.vault_id
        )

    elif page == "Accounts":
        from views.accounts import show_accounts

        render_profiled_page(
            page,
            show_accounts,
            st.session_state.vault_id
        )

    elif page == "Transactions":
        from views.transactions import show_transactions

        render_profiled_page(
            page,
            show_transactions,
            st.session_state.vault_id
        )

    elif page == "Planning":
        from views.planning import show_planning

        render_profiled_page(
            page,
            show_planning,
            st.session_state.vault_id
        )

    elif page == "Settings":
        from views.settings import show_settings

        render_profiled_page(
            page,
            show_settings,
            st.session_state.vault_id,
            st.session_state.is_admin
        )

    elif page == "Categories":
        from views.categories import show_categories

        render_profiled_page(
            page,
            show_categories,
            st.session_state.vault_id
        )

    elif page == "Transfers":
        from views.transfers import show_transfers

        render_profiled_page(
            page,
            show_transfers,
            st.session_state.vault_id
        )

    elif page == "Wishlist":
        from views.wishlist import show_wishlist

        render_profiled_page(
            page,
            show_wishlist,
            st.session_state.vault_id
        )

    elif page == "Reports":
        from views.reports import show_reports

        render_profiled_page(
            page,
            show_reports,
            st.session_state.vault_id
        )

    elif page == "Shared Expenses":
        from views.shared_expenses import show_shared_expenses

        render_profiled_page(
            page,
            show_shared_expenses,
            st.session_state.vault_id,
            st.session_state.vault_name
        )

    elif page == "Bills":
        from views.shared_auxiliary import show_shared_bills

        render_profiled_page(
            page,
            show_shared_bills,
            st.session_state.vault_id
        )
