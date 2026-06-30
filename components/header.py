import streamlit as st

from components.add_transaction_modal import (
    add_transaction_dialog
)
from db.dashboard import (
    is_setup_complete
)


def dashboard_header():
    
    if "show_transaction_dialog" not in st.session_state:
        st.session_state.show_transaction_dialog = False

    setup_complete = is_setup_complete(st.session_state.vault_id)

    col1, col2 = st.columns([4.5, 1.5])

    with col1:

        st.markdown(
            """
            <div class="dashboard-header">
                <h1>Money Vault</h1>
                <p>Your financial snapshot</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:

        st.write("")
        if setup_complete:
            if st.button(
                "🧾 Record Transaction",
                use_container_width=True
            ):
                st.session_state.show_transaction_dialog = True
        else:
            st.button(
                "🧾 Record Transaction",
                use_container_width=True,
                disabled=True
            )

    if (
        setup_complete
        and
        st.session_state.show_transaction_dialog
    ):
        st.session_state.show_transaction_dialog = False

        add_transaction_dialog(
            st.session_state.vault_id
        )
