# SmartRent (smartrent2)

SmartRent is a Flask + MySQL web app for rental property management with role-based dashboards for **Landlords**, **Tenants**, **Agents**, and **Service Providers**.

## What it does

- **Authentication & roles**: register/login and redirect users to the correct dashboard by role (`tenant`, `landlord`, `agent`, `service_provider`).
- **Landlord portal**: property/unit/tenant overview, rent collection status, notices, maintenance ticket overview, and lease agreements (including shareable signing links).
- **Tenant portal**: view profile, payments, bills, notices, and submit maintenance requests.
- **Agent portal**: manage landlords, properties, units, tenants; record payments; generate tenant receipts; view penalties/wallet and reports.
- **Reports**: generates PDF reports (income, expenses, occupancy, arrears).
- **Uploads**: stores uploaded images under `static/uploads` (property images, service-provider work photos).

## Tech stack

- **Backend**: Flask (`app.py` + blueprints under `blueprints/`)
- **DB**: MySQL using `flask_mysqldb` with a direct `MySQLdb` fallback (`extensions.py`)
- **Templating/UI**: Jinja2 templates under `templates/`
- **PDFs**: `reportlab` (see `blueprints/reports.py`)
- **Optional payments integration**: `payhero.py` contains PayHero (M-Pesa) helper functions; some UI references PayHero endpoints that are not currently wired to Flask routes.

## Project layout

- `app.py` - Flask app factory and blueprint registration
- `config.py` - configuration loaded from environment variables
- `extensions.py` - MySQL helpers + best-effort DB bootstrap for some tables/columns
- `helpers.py` - decorators and shared utilities (auth guard, uploads, stats helpers)
- `blueprints/` - route modules for each area (auth, landlord, tenant, agent, properties, reports, service)
- `templates/` - HTML templates for dashboards and pages
- `static/` - CSS/JS/images and runtime uploads (`static/uploads/`)

## Getting started (local dev)

### 1) Prerequisites

- Python 3.10+ (a local `.venv` folder exists in this repo, but any venv is fine)
- A running MySQL server (local or remote)

### 2) Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3) Configure environment variables

Create a `.env` file in the repo root (the app loads it via `python-dotenv` in `config.py`):

```env
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DB=smartrent

# Optional (only needed if you later wire PayHero routes)
PAYHERO_USERNAME=
PAYHERO_PASSWORD=
PAYHERO_CHANNEL_ID=
PAYHERO_CALLBACK_URL=
```

### 4) Database notes

This project expects an existing MySQL schema with core tables such as `users`, `properties`, `units`, `tenants`, `payments`, `bills`, `notices`, and `maintenance_requests`.

On startup, the app also attempts (best-effort) to create/adjust a few tables/columns automatically in `extensions.py`:

- `leases` table
- `agent_landlords` table
- `transactions` table
- `units.tenant_id` column + foreign key fixups
- `payments.due_date` and `payments.penalty_amount` columns

If you're starting from a fresh database, you may need to create the remaining tables manually (or add a schema/migrations workflow).

### 5) Run the app

Option A (direct):

```powershell
python app.py
```

Option B (Flask CLI):

```powershell
$env:FLASK_APP="app:create_app"
flask run --debug
```

Then open:

- Landing page: `http://127.0.0.1:5000/`
- Login: `http://127.0.0.1:5000/login`
- Register: `http://127.0.0.1:5000/register`

## Role quick guide

- **Tenant**: `/tenant-dashboard`, `/payments`, `/bills`, `/services`, `/notices`
- **Landlord**: `/landlord_dashboard`, properties/units management, rent collection, notices, maintenance, lease agreements
- **Agent**: `/agent-dashboard` plus management pages for landlords/properties/units/tenants and payment recording
- **Service provider**: `/service-dashboard` and demo job workflows; work photos are saved under `static/uploads/work/`

## Security

- Keep `.env` out of version control (it is ignored by `.gitignore`).
- If you ever committed real PayHero credentials to git history, rotate them.
