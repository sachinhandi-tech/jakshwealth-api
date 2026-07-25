# jakshwealth-api

Backend API for **JakshWealth**. The SPA talks to a small set of Python Lambdas
behind API Gateway: users sign in through Okta, the API verifies group
membership, exposes public app metadata, and serves protected business data
(stock analysis, charts, admin, and future features).

Each Lambda under `lambda/` is self-contained. Configuration comes from a single
per-environment AWS secret (`{ENVIRONMENT}/jakshwealth/config`), with optional
local overrides for development. See **Getting started** and **API layout** below.

This repository mirrors the layout of the upstream SSA API
(`hpp-self-service-analytics-api`) but is branded and deployed independently for
JakshWealth (`jw_*` Lambdas, `/jw-api` routes).

## Branching strategy

Feature-based workflow. Long-lived branches map to environments; feature work
always starts from `main`.

| Branch | Purpose |
|--------|---------|
| `main` | Source of truth. All feature branches are created from here. |
| `dev` | Shared development environment after local work is validated. |
| `test` | QA / test environment (`ENVIRONMENT=test`). |
| `release` | Release candidate — code here ships in the next earliest release. |

## Getting started (local development)

### Prerequisites

- Python 3.12+
- AWS credentials to read `dev/jakshwealth/config` in Secrets Manager (optional)
- Network access to Okta

### Setup

```bash
git clone <repo-url>
cd jakshwealth-api
git checkout main && git pull
git checkout -b feature/your-feature-name

cp .env.example .env
cp config.local.example.json config.local.json
chmod +x run-api.sh
./run-api.sh
```

Server: **http://localhost:3000**. `run-api.sh` creates a venv and installs
dependencies.

### Local configuration

When `ENVIRONMENT=local`, config loads in this order (highest wins):

**process env → `config.local.json` → `dev/jakshwealth/config` secret**

Set `CONFIG_SKIP_AWS=true` in `.env` to run offline from `config.local.json`
only.

### Okta bypass (local and dev only)

Set `JW_BYPASS_OKTA_AUTH=true` in `config.local.json` (local) or in the
`dev/jakshwealth/config` secret (deployed dev). Bypass is **ignored** when
`ENVIRONMENT` is `test` or `prod`.

Flow when bypass is on:

1. `GET app-config` returns `"bypassOktaAuth": true`.
2. The UI skips Okta and redirects to `token-auth/?bypass=true&redirect=true`.
3. The API issues a `jw-bypass.*` token and redirects the browser to
   `/authorize#accessToken=...`.

### Smoke test

```bash
curl http://localhost:3000/jw-api/app-config
curl http://localhost:3000/jw-api/secure-data/stock-universe -H 'Authorization: Bearer <token>'
curl -X POST http://localhost:3000/jw-api/secure-data/stock-scan \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"symbols":["RELIANCE","TCS"],"minScore":60}'
```

## API layout

Four Lambdas make up the API:

| Lambda | Path | Role |
|--------|------|------|
| `jw_authentication` | `/jw-api/token-auth` | Okta token exchange, refresh, validation |
| `jw_authorization` | *(API Gateway authorizer)* | JWT verification + group membership |
| `jw_app_config` | `/jw-api/app-config` | Public app metadata and feature flags |
| `jw_secure_data` | `/jw-api/secure-data/*` | Protected business API |

### `jw_secure_data` routes

| Path | Method | Purpose |
|------|--------|---------|
| `/jw-api/secure-data/stock-universe` | GET | NSE symbol universe |
| `/jw-api/secure-data/stock-scan` | POST | HH-HL weekly scanner |
| `/jw-api/secure-data/fetch-charts` | POST | Chart data (optional Databricks) |
| `/jw-api/secure-data/ai-chat` | POST | AI-assisted querying |
| `/jw-api/secure-data/admin` | GET | Admin / feature flags |

New features: add `lambda/jw_secure_data/features/<name>/` and register in
`features/__init__.py`.

## Tests

```bash
pytest lambda/jw_authentication lambda/jw_authorization lambda/jw_secure_data lambda/jw_app_config -v
```

## Deployment

Uses **jakshwealth-infra** for platform modules and API Gateway shell:

| Repo | Role |
|------|------|
| **jakshwealth-infra** | UI S3/CloudFront, `jw-api` REST API shell, reusable `deploy/*` modules |
| **jakshwealth-api** (this repo) | Lambdas, API integrations, stage deploy |

```bash
# Sibling checkout (local Terraform module paths)
../jakshwealth-infra/deploy/lambda

# Generate Terraform
cd automation_codes/python_scripts && python generate_tf.py --env dev --rest_api jw-api
```

Jenkins clones `jakshwealth-infra` before Terraform apply. Configure personal AWS
via `aws configure --profile jakshwealth` and fill `.cicd/build_props/*.properties`
(`account_number`, `aws_profile`). See `../jakshwealth-infra/docs/AWS_PERSONAL_SETUP.md`.

Upstream app reference: `hpp-self-service-analytics-api` (structural pattern only).
