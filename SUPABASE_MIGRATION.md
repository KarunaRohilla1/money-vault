# Money Vault Supabase Migration

Money Vault now stores application data in Supabase PostgreSQL.

## Required Streamlit Secrets

Add these in Streamlit Community Cloud under app settings > Secrets:

```toml
SUPABASE_DB_URL = "<pooled-postgres-connection-url-from-supabase>"
SUPABASE_URL = "https://PROJECT_REF.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

`SUPABASE_DB_URL` can also be named `DATABASE_URL`. Use Supabase's pooled PostgreSQL connection string for Streamlit Cloud.

## Manual Supabase Steps

1. Create a Supabase project.
2. Open Project Settings > Database and copy the pooled PostgreSQL connection string.
3. Replace `[YOUR-PASSWORD]` in the copied connection string with your database password.
4. Add the Streamlit secrets above.
5. Run the schema in Supabase SQL Editor using `supabase/schema.sql`, or let the app create the schema on startup.
6. Run the one-time migration script from your local machine:

```powershell
python scripts/migrate_sqlite_to_supabase.py --sqlite-path data/money.db
```

The script preserves IDs and relationships, then resets PostgreSQL identity sequences so future inserts continue correctly.

## Local Environment Variables

For local development, set:

```powershell
$env:SUPABASE_DB_URL="<pooled-postgres-connection-url-from-supabase>"
$env:SUPABASE_URL="https://PROJECT_REF.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
```

Never commit real Supabase credentials.
