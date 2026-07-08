import streamlit as st


def show_template_dialog(
    title,
    name_label,
    account_label,
    current_name,
    current_amount,
    current_due_day,
    current_account_id,
    accounts,
    on_save,
    on_delete,
    session_key,
    read_only=False
):

    @st.dialog(title)
    def dialog():

        account_map = {
            account[1]: account[0]
            for account in accounts
        }

        account_names = list(
            account_map.keys()
        )

        if not account_names:
            st.warning(
                "Create an account before editing this item."
            )
            if st.button(
                "Close",
                use_container_width=True
            ):
                st.session_state[session_key] = None
                st.rerun()
            return

        current_index = next(
            (
                i
                for i, account in enumerate(accounts)
                if account[0] == current_account_id
            ),
            0
        )

        name = st.text_input(
            name_label,
            value=current_name,
            disabled=read_only
        )

        amount = st.number_input(
            "Amount",
            value=float(current_amount),
            min_value=0.0,
            step=0.01,
            placeholder="Enter Amount",
            format="%.2f",
            disabled=read_only
        )

        due_day = st.number_input(
            "Due Day",
            value=int(current_due_day),
            min_value=1,
            max_value=31,
            disabled=read_only
        )

        selected_account = st.selectbox(
            account_label,
            account_names,
            index=current_index,
            disabled=read_only
        )

        st.divider()

        col1, col2, col3 = st.columns(3)

        with col1:

            if st.button(
                "Save",
                use_container_width=True,
                disabled=read_only
            ):

                cleaned_name = name.strip()

                if not cleaned_name:

                    st.error(
                        f"{name_label} is required."
                    )

                    st.stop()

                if amount <= 0:

                    st.error(
                        "Amount must be greater than 0."
                    )

                    st.stop()

                on_save(
                    cleaned_name,
                    amount,
                    due_day,
                    account_map[selected_account]
                )

                st.session_state[session_key] = None

                st.rerun()

        with col2:

            if st.button(
                "Delete",
                use_container_width=True,
                disabled=read_only
            ):

                on_delete()

                st.session_state[session_key] = None

                st.rerun()

        with col3:

            if st.button(
                "Cancel",
                use_container_width=True
            ):

                st.session_state[session_key] = None

                st.rerun()

    dialog()
