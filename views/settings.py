import streamlit as st

from db.postgres import IntegrityError
from db.vaults import (
    create_vault,
    delete_vault,
    demote_admin,
    get_admin_count,
    get_all_vaults,
    get_vault_by_id,
    get_vault_share_ids,
    promote_to_admin,
    update_vault
)


def vault_initial(name):
    return (name.strip()[:1] or "V").upper()


def vault_share_options(vaults, current_vault_id):
    return {
        vault[1]: vault[0]
        for vault in vaults
        if vault[0] != current_vault_id
    }


def refresh_current_vault(vault_id, name, is_admin):
    if st.session_state.get("vault_id") == vault_id:
        st.session_state.vault_name = name
        st.session_state.is_admin = bool(is_admin)


@st.dialog("Create Vault")
def create_vault_dialog():
    render_create_vault_form("create_vault_dialog")


@st.dialog("Edit Vault")
def edit_vault_dialog(vault):
    vault_id, name, is_admin, month_start_day, vault_type = vault
    vaults = get_all_vaults()
    share_options = vault_share_options(
        vaults,
        vault_id
    )
    selected_share_ids = get_vault_share_ids(
        vault_id
    )
    selected_share_names = [
        share_name
        for share_name, share_id in share_options.items()
        if share_id in selected_share_ids
    ]

    with st.form(f"edit_vault_{vault_id}"):
        new_name = st.text_input(
            "Vault Name",
            value=name
        )
        new_pin = st.text_input(
            "New PIN",
            type="password",
            placeholder="Leave blank to keep current PIN"
        )

        new_vault_type = st.selectbox(
            "Vault Type",
            ["Individual", "Shared"],
            index=0 if vault_type != "Shared" else 1
        )

        selected_share_names = st.multiselect(
            "Shared With",
            list(share_options.keys()),
            default=selected_share_names
        )

        save_clicked, cancel_clicked = st.columns(2)

        with save_clicked:
            submitted = st.form_submit_button(
                "Save Changes",
                use_container_width=True
            )

        with cancel_clicked:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

        if cancelled:
            st.rerun()

        if submitted:
            shared_vault_ids = [
                share_options[share_name]
                for share_name in selected_share_names
            ] if new_vault_type == "Shared" else []

            if new_vault_type == "Shared" and not shared_vault_ids:
                st.error("Choose at least one user for a shared vault.")
                st.stop()

            if new_vault_type == "Individual":
                shared_vault_ids = []

            new_name = new_name.strip()

            if not new_name:
                st.error("Vault name is required.")
                st.stop()

            if new_pin and len(new_pin) < 4:
                st.error("PIN must be at least 4 characters.")
                st.stop()

            try:
                update_vault(
                    vault_id,
                    new_name,
                    pin=new_pin or None,
                    vault_type=new_vault_type,
                    shared_vault_ids=shared_vault_ids
                )
            except ValueError as error:
                st.error(str(error))
                st.stop()
            except IntegrityError:
                st.error("A vault with this name already exists.")
                st.stop()

            refresh_current_vault(
                vault_id,
                new_name,
                is_admin
            )
            st.rerun()


@st.dialog("Delete Vault")
def delete_vault_dialog(vault):
    vault_id, name, is_admin, _month_start_day, _vault_type = vault

    st.warning(
        f"Delete '{name}'? This removes its accounts, transactions, planning data, categories, and wishlist."
    )

    left, right = st.columns(2)

    with left:
        if st.button(
            "Delete",
            use_container_width=True
        ):
            if get_admin_count() == 1 and bool(is_admin):
                st.error("Cannot delete the last admin.")
                st.stop()

            delete_vault(vault_id)

            if st.session_state.get("vault_id") == vault_id:
                st.session_state.authenticated = False
                st.session_state.vault_id = None
                st.session_state.vault_name = None
                st.session_state.is_admin = False

            st.rerun()

    with right:
        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.rerun()


def render_create_vault_form(form_key):
    vaults = get_all_vaults()

    with st.form(form_key):
        name_col, pin_col, admin_col = st.columns(
            [1.4, 1.1, 1.3],
            vertical_alignment="center"
        )

        with name_col:
            name = st.text_input(
                "Vault Name",
                placeholder="Enter vault name",
                key=f"{form_key}_name"
            )

        with pin_col:
            pin = st.text_input(
                "PIN",
                type="password",
                placeholder="Enter 4-digit PIN",
                key=f"{form_key}_pin"
            )

        with admin_col:
            is_admin = st.checkbox(
                "Make this vault an admin vault.",
                key=f"{form_key}_admin"
            )

        vault_type = st.selectbox(
            "Vault Type",
            ["Individual", "Shared"],
            key=f"{form_key}_vault_type"
        )

        share_options = {
            vault[1]: vault[0]
            for vault in vaults
        }

        selected_share_names = st.multiselect(
            "Shared With",
            list(share_options.keys()),
            key=f"{form_key}_shared_with"
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Create Vault",
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
            shared_vault_ids = [
                share_options[share_name]
                for share_name in selected_share_names
            ] if vault_type == "Shared" else []

            if not name:
                st.error("Vault name is required.")
                st.stop()

            if not pin:
                st.error("PIN is required.")
                st.stop()

            if len(pin) < 4:
                st.error("PIN must be at least 4 characters.")
                st.stop()

            if vault_type == "Shared" and not shared_vault_ids:
                st.error("Choose at least one user for a shared vault.")
                st.stop()

            try:
                create_vault(
                    name,
                    pin,
                    is_admin,
                    vault_type=vault_type,
                    shared_vault_ids=shared_vault_ids
                )
            except IntegrityError:
                st.error("A vault with this name already exists.")
                st.stop()

            st.rerun()


def render_vault_actions(vault):
    vault_id, name, is_admin, _month_start_day, _vault_type = vault

    if hasattr(st, "popover"):
        with st.popover("⋮"):
            if st.button(
                "Edit",
                key=f"edit_vault_{vault_id}",
                use_container_width=True
            ):
                st.session_state.edit_vault_id = vault_id
                st.rerun()

            if bool(is_admin):
                if st.button(
                    "Demote",
                    key=f"demote_vault_{vault_id}",
                    use_container_width=True
                ):
                    if get_admin_count() == 1:
                        st.error("Cannot remove the last admin.")
                        st.stop()

                    demote_admin(name)
                    refresh_current_vault(
                        vault_id,
                        name,
                        False
                    )
                    st.rerun()
            else:
                if st.button(
                    "Promote",
                    key=f"promote_vault_{vault_id}",
                    use_container_width=True
                ):
                    promote_to_admin(name)
                    refresh_current_vault(
                        vault_id,
                        name,
                        True
                    )
                    st.rerun()

            if st.button(
                "Delete",
                key=f"delete_vault_{vault_id}",
                use_container_width=True
            ):
                st.session_state.delete_vault_id = vault_id
                st.rerun()

    elif st.button(
        "⋮",
        key=f"vault_actions_{vault_id}"
    ):
        st.session_state.edit_vault_id = vault_id
        st.rerun()


def render_vaults_table(vaults):
    st.markdown(
        """
        <div class="mv-settings-table-head">
            <div>Vault Name</div>
            <div>Type</div>
            <div>Is Admin</div>
            <div>Actions</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    for vault in vaults:
        vault_id, name, is_admin, _month_start_day, vault_type = vault

        row = st.columns(
            [2.6, 1.0, 1.1, 0.55],
            vertical_alignment="center"
        )

        with row[0]:
            st.markdown(
                f"""
                <div class="mv-settings-vault-name">
                    <span class="mv-settings-avatar">{vault_initial(name)}</span>
                    <strong>{name}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )

        with row[1]:
            st.markdown(
                f'<div class="mv-settings-type">{vault_type}</div>',
                unsafe_allow_html=True
            )

        with row[2]:
            status_class = "yes" if is_admin else "no"
            icon = "check_circle" if is_admin else "close"
            label = "Yes" if is_admin else "No"
            st.markdown(
                f"""
                <div class="mv-settings-admin {status_class}">
                    <span class="material-symbols-outlined">{icon}</span>
                    {label}
                </div>
                """,
                unsafe_allow_html=True
            )

        with row[3]:
            render_vault_actions(vault)

        st.markdown(
            '<div class="mv-settings-row-divider"></div>',
            unsafe_allow_html=True
        )


def render_user_details(vault):
    vault_id, name, is_admin, month_start_day, _vault_type = vault

    st.markdown(
        """
        <div class="mv-settings-card mv-settings-user-card">
            <h3>User Details</h3>
            <p>Manage your own vault profile and month setup.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.form("user_details_form"):
        name_col, pin_col, day_col = st.columns(
            [1.4, 1.1, 1.0],
            vertical_alignment="center"
        )

        with name_col:
            new_name = st.text_input(
                "Name",
                value=name
            )

        with pin_col:
            new_pin = st.text_input(
                "New PIN",
                type="password",
                placeholder="Leave blank to keep current PIN"
            )

        with day_col:
            new_month_start_day = st.number_input(
                "Month Start Date",
                min_value=1,
                max_value=28,
                value=int(month_start_day or 1),
                step=1
            )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Save Details",
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
                st.error("Name is required.")
                st.stop()

            if new_pin and len(new_pin) < 4:
                st.error("PIN must be at least 4 characters.")
                st.stop()

            try:
                update_vault(
                    vault_id,
                    new_name,
                    pin=new_pin or None,
                    month_start_day=new_month_start_day
                )
            except ValueError as error:
                st.error(str(error))
                st.stop()
            except IntegrityError:
                st.error("A vault with this name already exists.")
                st.stop()

            refresh_current_vault(
                vault_id,
                new_name,
                is_admin
            )
            st.rerun()


def show_settings(vault_id, is_admin):
    current_vault = get_vault_by_id(vault_id)

    if not current_vault:
        st.error("Vault not found.")
        st.stop()

    vaults = get_all_vaults()

    edit_vault_id = None
    delete_vault_id = None

    if is_admin:
        edit_vault_id = st.session_state.pop("edit_vault_id", None)
        delete_vault_id = st.session_state.pop("delete_vault_id", None)
    else:
        st.session_state.pop("edit_vault_id", None)
        st.session_state.pop("delete_vault_id", None)

    if is_admin:
        if edit_vault_id:
            vault = next(
                (
                    item for item in vaults
                    if item[0] == edit_vault_id
                ),
                None
            )
            if vault:
                edit_vault_dialog(vault)

        if delete_vault_id:
            vault = next(
                (
                    item for item in vaults
                    if item[0] == delete_vault_id
                ),
                None
            )
            if vault:
                delete_vault_dialog(vault)

    title_col, action_col = st.columns(
        [3, 1],
        vertical_alignment="center"
    )

    with title_col:
        st.markdown(
            """
            <div class="mv-settings-title">
                <h2>Settings</h2>
                <p>Manage your vaults and control access.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with action_col:
        if is_admin:
            if st.button(
                "+  Create Vault",
                key="open_create_vault_dialog",
                use_container_width=True
            ):
                create_vault_dialog()

    render_user_details(
        current_vault
    )

    if not is_admin:
        return

    st.markdown(
        """
        <div class="mv-settings-card">
            <h3>Vaults</h3>
            <p>All your vaults in one place.</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_vaults_table(vaults)

    st.markdown(
        """
        <div class="mv-settings-card mv-settings-create-card">
            <h3>Create Vault</h3>
            <p>Create a new vault to organize your finances.</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_create_vault_form("create_vault")
