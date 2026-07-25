# Reference

JakshWealth API replicates the **file and folder structure** of
`hpp-self-service-analytics-api` (SSA) with JakshWealth naming:

| SSA (reference) | JakshWealth (this repo) |
|-----------------|-------------------------|
| `ssa_*` Lambdas | `jw_*` Lambdas |
| `/ssa-api` | `/jw-api` |
| `{env}/hppssa/config` | `{env}/jakshwealth/config` |
| `ssa_log.py` | `jw_log.py` |

Use the SSA repo when comparing auth flows, Terraform generators, or Jenkins
stages. Do not copy Cigna-specific account IDs, VPC names, or Okta federation
URLs — configure those for your personal AWS and Okta tenant in this repo.
