# YSocial Configurator

YSocial Configurator is the administrative web platform used to configure social simulation experiments.

This repository is **not** the full YSocial runtime stack and does **not** execute experiments.

## Scope

This project is focused on configuration workflows:

- experiment metadata and setup
- users and roles management
- agents/populations and related settings
- client configuration pages
- dashboard/admin views for configured experiments

## Not Included In This Build

The following capabilities are intentionally removed/disabled:

- experiment execution (start/stop/load/run clients)
- scheduling and scheduler monitoring
- execution status tracking and watchdog flows
- external process orchestration
- telemetry components
- LLM integrations and LLM annotation flows
- JupyterLab/notebook integrations
- legacy package distribution notes and old runtime features

## Authentication

Supported login methods:

- email/password
- social OAuth login/signup
- ORCID OAuth login/signup

OAuth-created users default to role `researcher`.

Full setup and route documentation:

- [Authentication Guide](docs/AUTHENTICATION.md)

## Quick Start (Source)

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the configurator:

```bash
python y_social.py --host localhost --port 8080
```

4. Open:

- <http://localhost:8080>

Default admin credentials:

- email: `admin@y-not.social`
- password: `admin`

## Database

Supported backends:

- SQLite (default)
- PostgreSQL

Select backend at startup:

```bash
python y_social.py --db sqlite
python y_social.py --db postgresql
```

## Repository Notes

- This README documents the current configurator-only behavior.
- If you need the full simulation runtime, use the full YSocial system repository/runtime stack, not this one.
