import tempfile
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

import database


def run():

    with tempfile.TemporaryDirectory() as tmp:

        database.DB_PATH = str(
            Path(tmp) / "money.db"
        )

        database.initialize_database()
        database.migrate_database()

        database.create_vault(
            "Vault",
            "1234",
            True
        )

        vault_id = database.get_vaults()[0][0]

        assert any(
            category[2] == "Default"
            for category in database.get_categories(vault_id)
        )

        database.add_account(
            vault_id,
            "Salary",
            "Salary Account",
            10000
        )

        database.add_account(
            vault_id,
            "Savings",
            "Savings Account",
            2000
        )

        accounts = database.get_accounts(
            vault_id
        )

        salary = next(
            account[0]
            for account in accounts
            if account[1] == "Salary"
        )

        savings = next(
            account[0]
            for account in accounts
            if account[1] == "Savings"
        )

        assert database.get_primary_account(vault_id)[0] == salary

        database.set_primary_account(savings)

        assert database.get_primary_account(vault_id)[0] == savings
        assert database.get_accounts(vault_id)[0][0] == savings

        group_id = database.add_transfer(
            vault_id,
            salary,
            savings,
            "2026-06-11",
            1500,
            "Move"
        )

        assert database.get_account_balance(salary) == 8500
        assert database.get_account_balance(savings) == 3500

        database.update_transfer(
            group_id,
            savings,
            salary,
            "2026-06-12",
            500,
            "Back"
        )

        assert database.get_account_balance(salary) == 10500
        assert database.get_account_balance(savings) == 1500

        database.delete_transfer(
            group_id
        )

        assert database.get_account_balance(salary) == 10000
        assert database.get_account_balance(savings) == 2000

        database.add_income_template(
            vault_id,
            "Salary",
            5000,
            1,
            salary
        )

        income_id = database.get_income_templates(
            vault_id
        )[0][0]

        database.save_income_status(
            income_id,
            6,
            2026,
            5000,
            "RECEIVED"
        )

        assert database.get_account_balance(salary) == 15000

        database.save_income_status(
            income_id,
            6,
            2026,
            0,
            "CANCELLED"
        )

        assert database.get_account_balance(salary) == 10000

        database.add_commitment(
            vault_id,
            "Rent",
            1200,
            5,
            salary
        )

        commitment_id = database.get_commitments(
            vault_id
        )[0][0]

        database.finalize_month(
            vault_id,
            6,
            2026,
            [
                {
                    "id": income_id,
                    "type": "income",
                    "action": "Carry Forward",
                    "amount": 5000
                },
                {
                    "id": commitment_id,
                    "type": "commitment",
                    "action": "Carry Forward",
                    "amount": 1200
                }
            ]
        )

        assert database.get_account_balance(salary) == 10000

        current_month_totals = database.get_monthly_planning_totals(
            vault_id,
            6,
            2026
        )
        assert current_month_totals["remaining_commitments"] == 0

        next_cycle = database.get_cycle(
            vault_id,
            7,
            2026
        )
        assert next_cycle[4] == "ACTIVE"

        income_status = database.get_income_status(
            income_id,
            7,
            2026
        )
        assert income_status[0] == 10000
        assert income_status[1] == "PENDING"

        commitment_status = database.get_obligation_status(
            commitment_id,
            7,
            2026
        )
        assert commitment_status[0] == 2400
        assert commitment_status[1] == "PENDING"

        planning_totals = database.get_monthly_planning_totals(
            vault_id,
            7,
            2026
        )
        assert planning_totals["income"] == 10000
        assert planning_totals["planned_commitments"] == 2400
        assert planning_totals["remaining_commitments"] == 2400

        assert database.get_dashboard_cycle(vault_id) == (
            7,
            2026
        )

        default_category = next(
            category[0]
            for category in database.get_categories(vault_id)
            if category[2] == "Default"
        )

        database.add_transaction(
            vault_id,
            salary,
            "2026-07-02",
            300,
            default_category,
            "Expense",
            "Groceries"
        )

        dashboard = database.get_dashboard_summary(vault_id)
        assert dashboard["month"] == 7
        assert dashboard["year"] == 2026
        assert dashboard["primary_account_name"] == "Savings"
        assert dashboard["primary_account_balance"] == 2000
        assert dashboard["available_cash"] == 9700
        assert dashboard["remaining_commitments"] == 2400
        assert dashboard["expenses"] == 300
        assert dashboard["safe_to_spend"] == 7300

        database.add_wishlist_category(
            vault_id,
            "Photography"
        )

        assert any(
            category[2] == "Photography"
            for category in database.get_wishlist_categories(vault_id)
        )

        database.add_wishlist_item(
            vault_id,
            "Camera",
            "Photography",
            100000,
            notes="Wishlist smoke test"
        )

        wishlist_summary = database.get_wishlist_summary(
            vault_id
        )
        assert wishlist_summary["total_items"] == 1
        assert wishlist_summary["total_cost"] == 100000
        assert wishlist_summary["total_saved"] == 0
        assert wishlist_summary["progress"] == 0

        wishlist_item = database.get_wishlist_items(
            vault_id,
            category="Photography"
        )[0]
        assert wishlist_item[1] == "Camera"
        assert wishlist_item[2] == "Photography"

        database.update_wishlist_item(
            wishlist_item[0],
            "Camera",
            "Photography",
            120000,
            0,
            None,
            None,
            "",
            "Updated"
        )

        wishlist_summary = database.get_wishlist_summary(
            vault_id
        )
        assert wishlist_summary["total_cost"] == 120000
        assert wishlist_summary["total_saved"] == 0
        assert wishlist_summary["progress"] == 0

        database.delete_wishlist_item(
            wishlist_item[0]
        )

        assert database.get_wishlist_summary(
            vault_id
        )["total_items"] == 0


if __name__ == "__main__":

    run()

    print("smoke money flow passed")
