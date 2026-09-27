# Supabase PostgreSQL Setup & Configuration

Money Vault uses Supabase PostgreSQL for persistent multi-vault application data.

---

## 1. Database Provisioning

1. Create a project in [Supabase](https://supabase.com).
2. Open **Project Settings > Database** in the Supabase Dashboard.
3. Locate the **Connection string** section and copy the **URI (Transaction pooler / Session pooler)**.
4. Replace `[YOUR-PASSWORD]` in the connection string with your actual database password.

---

## 2. Schema Setup

Initialize the required tables, constraints, and indexes:
1. Navigate to the **SQL Editor** in the Supabase dashboard.
2. Open [`supabase/schema.sql`](supabase/schema.sql) from this repository.
3. Paste the contents into the SQL Editor and run the script.

The schema establishes:
- Vaults, members, and user profiles (`vaults`, `vault_members`, `profiles`, `user_recovery_codes`)
- Financial entities (`accounts`, `categories`, `transactions`, `transfers`)
- Planning & commitments (`income_templates`, `commitments`, `financial_cycles`, `cycle_history`)
- Shared vault expenses, bills, and settlements (`shared_expenses`, `shared_bills`, `shared_settlements`, `transaction_shares`)
- Smart SMS capture inbox (`capture_drafts`)
- Wishlist items and categories (`wishlist_items`, `wishlist_categories`)

---

## 3. Environment Variables Configuration

Set the database connection parameters in your backend environment (or `.env` file):

```bash
# Database connection string (pooled recommended for serverless/containers)
SUPABASE_DB_URL="postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"

# Supabase API credentials
SUPABASE_URL="https://[PROJECT_REF].supabase.co"
SUPABASE_JWT_SECRET="your-supabase-jwt-secret"
```

> **Security Note:** Never commit production credentials or connection strings containing real passwords to version control.
