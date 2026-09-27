# Money Vault Backend

FastAPI REST API backend powering the **Money Vault Mobile** application.

---

## Overview

Money Vault provides a secure, multi-vault financial tracking platform with support for:
- **Authentication & Security:** Username and PIN authentication, JWT session tokens, recovery codes, and role-based vault access.
- **Personal & Shared Vaults:** Dedicated personal financial spaces alongside shared vaults for group expense splitting, bill management, and debt settlements.
- **Accounts & Categories:** Full lifecycle management for multiple account types (bank, credit card, cash, wallet) and categorized spending.
- **Financial Cycles & Planning:** Dynamic monthly cycle dates, income templates, recurring commitments, and cycle close workflows.
- **Smart SMS Capture:** Automated parsing and review inbox for incoming transaction messages with duplicate detection and merchant normalization.
- **Analytics & Reporting:** Spending breakdown by category, payment mode, and period, as well as shared vault balance and settlement histories.

---

## Tech Stack

- **Framework:** FastAPI (Python 3.12)
- **Server:** Uvicorn (ASGI)
- **Database:** PostgreSQL (Supabase)
- **Security:** PyJWT, bcrypt
- **Testing:** pytest

---

## Getting Started

### 1. Prerequisites

- Python 3.12+
- Supabase project (or PostgreSQL instance)

### 2. Installation

Clone the repository and set up a virtual environment:

```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy `.env.example` to `.env` and fill in the required values:

```powershell
cp .env.example .env
```

Key environment variables:
- `JWT_SECRET`: Secret key (minimum 32 bytes) used to sign session tokens.
- `SUPABASE_DB_URL`: Pooled PostgreSQL connection string from Supabase.
- `SUPABASE_URL`: Supabase project URL (`https://<project-ref>.supabase.co`).
- `SUPABASE_JWT_SECRET`: (Optional) Supabase JWT secret if validating Supabase tokens.
- `API_HOST`: Bind host (default: `0.0.0.0` for local testing with mobile devices/emulators).
- `API_PORT`: Bind port (default: `8001`).
- `CORS_ALLOWED_ORIGINS`: Comma-separated allowed origins (leave empty in development for `*`).

### 4. Database Setup

Provision the database schema in your Supabase project:
1. Open the **SQL Editor** in your Supabase dashboard.
2. Execute the script located in [`supabase/schema.sql`](supabase/schema.sql).

---

## Running the API

### Local Development Server

Run the local development launcher:

```powershell
python scripts/run_api_local.py
```

- **API Base URL:** `http://127.0.0.1:8001`
- **Interactive OpenAPI Docs:** `http://127.0.0.1:8001/docs`
- **Health Check:** `http://127.0.0.1:8001/health`

> **Note for Mobile Testing:** The server binds to `0.0.0.0`. Physical devices or Android emulators on the same network should connect via your LAN IP or `10.0.2.2:8001`.

---

## Running Tests

Execute the full automated backend test suite:

```powershell
python -m pytest
```

---

## Production Deployment

A production-ready [`Dockerfile`](Dockerfile) is included for containerized environments (Google Cloud Run, AWS ECS, Render, etc.):

```bash
docker build -t money-vault-api .
docker run -p 8080:8080 --env-file .env money-vault-api
```
