# Workshop screenshot checklist

Use synthetic/non-sensitive data where possible. Never capture AWS credentials,
secret values, account billing details, or unrelated resources.

| # | Screen to open | What must be visible | Evidence provided |
|---:|---|---|---|
| 1 | File Explorer or editor Explorer | New project root and main folders only | Shows the isolated project structure. |
| 2 | PowerShell after `pytest -q` | `48 passed` and no failure | Proves automated validation passed locally. |
| 3 | PowerShell after the CLI command | Success summary and row counts | Proves the real ZIP ran locally. |
| 4 | Editor/CSV preview | Header plus `user-xxx` and `prod-xxx` values | Proves original ID shapes remain. |
| 5 | Editor on `data_quality_report.json` | Row counts, `generated_*_id_count: 0`, ID check PASS | Provides machine-readable quality evidence. |
| 6 | PowerShell after `sam validate --lint` | Successful template validation | Proves the SAM definition is valid. |
| 7 | PowerShell after `sam build --no-use-container` | Successful build and no container use | Proves Docker-free packaging. |
| 8 | CloudFormation → Stacks | Stack status `CREATE_COMPLETE` | Proves AWS deployment completed. |
| 9 | CloudFormation → Resources | Bucket, function, role, permission, log group | Proves IaC resource ownership. |
| 10 | CloudFormation → Outputs | Bucket name, function name/ARN, prefixes | Supplies values used by later commands. |
| 11 | S3 console → generated bucket | Prefixes `incoming/`, `processed/`, `rejected/`, `reports/` | Shows the storage layout. |
| 12 | S3 → `incoming/` | `export.zip` object name and size | Proves the source object was uploaded. |
| 13 | Lambda → Function overview | S3 trigger with `incoming/` and `.zip` filters | Proves safe event routing. |
| 14 | Lambda → Runtime settings | Python 3.13 and arm64 | Proves required runtime configuration. |
| 15 | Lambda → Environment variables | Prefixes and three archive limits; no secrets | Proves configurable safety limits. |
| 16 | Lambda → Permissions | Execution role and scoped S3 policies | Proves least-privilege access. |
| 17 | Lambda → Monitor → CloudWatch logs | Success log with run ID and aggregate counts | Proves the cloud job finished and was monitored. |
| 18 | S3 → `processed/latest/` | `interactions_clean.csv` | Proves the current clean artifact exists. |
| 19 | S3 → `rejected/latest/` | `interactions_rejected.csv` | Proves rejected-data handling exists, even header-only. |
| 20 | S3 → `reports/latest/` | `data_quality_report.json` | Proves AWS-side report publication. |
| 21 | Athena Query editor | `ecommerce_pipeline` database | Proves the verification catalog exists. |
| 22 | Athena table details | `interactions_clean` schema and S3 location | Proves the clean CSV is queryable. |
| 23 | Athena query result | Event distribution counts | Reconciles Athena with the quality report. |
| 24 | Athena sample query | Twenty original `user-xxx`/`prod-xxx` rows | Proves IDs were not replaced. |
| 25 | Athena invalid-row checks | Four results equal to zero | Proves clean-output constraints. |
| 26 | Rendered architecture diagram | S3 → Lambda → outputs → Athena plus CloudWatch/SAM | Explains the end-to-end design. |
| 27 | PowerShell download command | Successful copy to `downloaded/interactions_clean.csv` | Identifies the artifact handed to the ML engineer. |

Items 6–25 and 27 require the user to deploy and operate the stack in their own
AWS account. A local result must not be presented as AWS evidence.
