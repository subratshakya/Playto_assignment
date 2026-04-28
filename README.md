# Playto Payout Engine

Full-stack payout engine built with Django, DRF, React, Tailwind, PostgreSQL-friendly data modeling, and Django-Q2 workers.

## What it does

- Maintains merchant balances as ledger entries in paise using `BigIntegerField`
- Computes `balance = credits - debits` from database queries only
- Tracks both `available_balance_paise` and `held_balance_paise`
- Creates payout requests with idempotency protection per merchant
- Holds funds immediately on payout creation
- Processes payouts asynchronously with success, failure, and stuck/retry paths
- Refunds failed payouts atomically back into the ledger
- Shows balances, transactions, bank accounts, and payout history in a React dashboard
- Auto-refreshes payout status in the dashboard every 5 seconds

## Project layout

- `backend/`: Django API, ledger, payout state machine, worker hooks, seed command, tests
- `frontend/`: React + Tailwind dashboard
- `EXPLAINER.md`: design walkthrough and implementation notes

## Quick start

### 1. PostgreSQL

```powershell
docker compose up -d postgres
```

### 2. Backend

```powershell
cd backend
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Run the worker in a second terminal:

```powershell
cd backend
python manage.py qcluster
```

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api/*` requests to `http://127.0.0.1:8000`.

## PostgreSQL configuration

The app falls back to SQLite only for local convenience. The intended challenge setup is PostgreSQL, and the concurrency behavior is designed around PostgreSQL row locking.

```env
POSTGRES_DB=playto
POSTGRES_USER=playto
POSTGRES_PASSWORD=playto
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

An example file is included at [backend/.env.example](/C:/Users/subra/Downloads/Playto/backend/.env.example).

## Seeded merchants

After `python manage.py seed_demo_data`, the app creates:

- `Blue Shop` with `INR 4,500.00`
- `Northwind Foods` with `INR 8,200.00`
- `Orbit Electronics` with `INR 12,500.00`

Each merchant also gets one demo bank account.

## API

### `GET /api/v1/merchants`

Returns all merchants with annotated balances, held balance, available balance, and bank accounts.

### `GET /api/v1/merchants/<merchant_id>/dashboard`

Returns one merchant, recent payouts, and recent ledger entries.

### `POST /api/v1/payouts`

Headers:

- `X-Merchant-Id`: merchant context for the request
- `Idempotency-Key`: required idempotency key, scoped per merchant for 24 hours

Body:

```json
{
  "amount_paise": 250000,
  "bank_account_id": 1
}
```

Behavior:

- Creates a `pending` payout
- Writes a debit ledger entry immediately to hold funds
- Returns the same response snapshot when the same merchant reuses the same `Idempotency-Key`

## Worker behavior

- `70%` chance: `pending -> processing -> completed`
- `20%` chance: `pending -> processing -> failed`, then refund credit is written
- `10%` chance: payout remains stuck in `processing`
- Each processing attempt schedules an exact Django-Q retry check at `30s`, `60s`, and `120s`
- After the third attempt window expires, the payout fails and is refunded atomically

## Tests

```powershell
cd backend
python manage.py test payouts
```

Included tests:

- idempotency replay test
- concurrent insufficient-funds test

## Verification completed in this workspace

- `python manage.py migrate`
- `python manage.py seed_demo_data`
- `python manage.py test payouts`
- `npm run build`

## Remaining submission steps

- deploy from `render.yaml` using Render Blueprint (free)
- run migrations and seed data on the deployed backend
- paste the live URL and repo URL into the submission form

## One-click deployment (Render Blueprint)

This repo includes `render.yaml` that provisions:

- PostgreSQL database (`playto-postgres`)
- Django API web service (`playto-backend`)
- Django-Q worker (`playto-worker`)
- static React frontend (`playto-frontend`)

### Deploy steps

1. Push this repo to GitHub.
2. In Render, click **New +** -> **Blueprint** and select this repo.
3. After first deploy, open the `playto-backend` shell and run:

```bash
python manage.py migrate
python manage.py seed_demo_data
```

4. In the frontend service (`playto-frontend`) set:

```env
VITE_API_BASE_URL=https://<your-backend-service>.onrender.com
```

5. Re-deploy the frontend service.

### Submission URLs

- **GitHub repo URL**: `https://github.com/subratshakya/Playto_assignment`
- **Live deployment URL**: use the frontend URL, for example:
  `https://playto-frontend.onrender.com`

# Playto_assignment
