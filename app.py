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

from views.accounts import show_accounts
from views.transactions import show_transactions
from views.categories import show_categories
from views.dashboard import show_dashboard
from views.settings import show_settings
from views.planning import show_planning
from views.transfers import show_transfers
from views.wishlist import show_wishlist
from views.reports import show_reports

def load_css():
    with open(
        "styles/main.css", encoding="utf-8"
    ) as f:
        st.markdown(
            f"<style>{f.read()}</style>",
            unsafe_allow_html=True
        )


@st.cache_resource(show_spinner=False)
def bootstrap_database():
    initialize_database()
    migrate_database()
    return True


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
        show_dashboard(st.session_state.vault_id)

    elif page == "Accounts":
        show_accounts(st.session_state.vault_id)

    elif page == "Transactions":
        show_transactions(
        st.session_state.vault_id
    )

    elif page == "Planning":
        show_planning(
        st.session_state.vault_id
    )

    elif page == "Settings":
        show_settings(
            st.session_state.vault_id,
            st.session_state.is_admin
        )

    elif page == "Categories":
        show_categories(
        st.session_state.vault_id)

    elif page == "Transfers":
        show_transfers(
            st.session_state.vault_id
        )

    elif page == "Wishlist":
        show_wishlist(
            st.session_state.vault_id
        )

    elif page == "Reports":
        show_reports(
            st.session_state.vault_id
        )
