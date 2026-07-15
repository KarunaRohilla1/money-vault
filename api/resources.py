from fastapi import HTTPException, status

from db.core import get_connection


def request_error(status_code, code, message):
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message
        }
    )


def bad_request(message):
    return request_error(
        status.HTTP_400_BAD_REQUEST,
        "VALIDATION_ERROR",
        message
    )


def not_found(message="Resource not found."):
    return request_error(
        status.HTTP_404_NOT_FOUND,
        "NOT_FOUND",
        message
    )


def int_vault_id(vault):
    return int(vault.id)


def account_belongs_to_vault(account_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM accounts
            WHERE id = ?
            AND vault_id = ?
            AND is_active = 1
            """,
            (
                account_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def category_accessible_to_vault(category_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM categories
            WHERE id = ?
            AND is_active = 1
            AND (
                vault_id = ?
                OR is_system = 1
            )
            """,
            (
                category_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def transaction_belongs_to_vault(transaction_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM transactions
            WHERE id = ?
            AND vault_id = ?
            AND is_deleted = 0
            """,
            (
                transaction_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def transfer_belongs_to_vault(transfer_group_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM transactions
            WHERE transfer_group_id = ?
            AND vault_id = ?
            AND is_deleted = 0
            LIMIT 1
            """,
            (
                transfer_group_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def commitment_belongs_to_vault(commitment_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM commitments
            WHERE id = ?
            AND vault_id = ?
            AND is_active = 1
            """,
            (
                commitment_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def income_template_belongs_to_vault(template_id, vault_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM income_templates
            WHERE id = ?
            AND vault_id = ?
            AND is_active = 1
            """,
            (
                template_id,
                vault_id
            )
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def require_account(account_id, vault_id):
    if not account_belongs_to_vault(
        account_id,
        vault_id
    ):
        raise not_found()


def require_category(category_id, vault_id):
    if not category_accessible_to_vault(
        category_id,
        vault_id
    ):
        raise not_found()


def require_transaction(transaction_id, vault_id):
    if not transaction_belongs_to_vault(
        transaction_id,
        vault_id
    ):
        raise not_found()


def require_transfer(transfer_group_id, vault_id):
    if not transfer_belongs_to_vault(
        transfer_group_id,
        vault_id
    ):
        raise not_found()


def require_commitment(commitment_id, vault_id):
    if not commitment_belongs_to_vault(
        commitment_id,
        vault_id
    ):
        raise not_found()


def require_income_template(template_id, vault_id):
    if not income_template_belongs_to_vault(
        template_id,
        vault_id
    ):
        raise not_found()
