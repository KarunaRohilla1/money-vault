import os
import time

import streamlit as st

from db.schema import (
    initialize_database,
    migrate_database
)
from db.vaults import (
    get_vaults,
    vault_exists,
    verify_pin
)


PROFILED_PAGES = {
    "Dashboard",
    "Accounts",
    "Transactions",
    "Planning",
    "Reports"
}

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
    if os.environ.get("MONEY_VAULT_RUN_RUNTIME_MIGRATIONS") == "1":
        initialize_database()
        migrate_database()
    return True


def render_profiled_page(page_name, render_function, *args):
    start = time.perf_counter()

    try:
        return render_function(*args)

    finally:
        elapsed = time.perf_counter() - start

        if page_name in PROFILED_PAGES:
            print(f"[money-vault perf] {page_name}: {elapsed:.3f}s")


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
            st.session_state.vault_id = vault[0]
            st.session_state.vault_name = vault[1]
            st.session_state.is_admin = bool(vault[3])

            st.rerun()

        else:
            st.error("Incorrect PIN")


# -------------------
# Logged In Area
# -------------------

else:

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

    if st.sidebar.button("Logout"):

        st.session_state.authenticated = False
        st.session_state.vault_id = None
        st.session_state.vault_name = None
        st.session_state.is_admin = False

        st.rerun()

    page = st.sidebar.radio(
        "Navigation",
        [
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
    )

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
