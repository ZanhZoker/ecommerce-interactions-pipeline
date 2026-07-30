# Amazon Athena verification

Athena is used only to query and verify the clean CSV. It never modifies or
re-encodes `USER_ID` or `ITEM_ID`.

1. Open **Amazon Athena → Query editor** in the same Region as the S3 bucket.
2. In **Settings**, set the query result location to
   `s3://<BUCKET_NAME>/athena-results/`.
3. Run `create_database.sql`.
4. In `create_table.sql`, replace `<BUCKET_NAME>` with the
   `DataBucketName` CloudFormation output, then run it.
5. Run individual statements from `sample_queries.sql`.
6. Capture the counts, the zero-invalid-row checks, and sample original IDs for
   the workshop evidence.

The table reads `s3://<BUCKET_NAME>/processed/latest/`, where the Lambda keeps
one current `interactions_clean.csv`. Run-scoped copies remain under
`processed/run_id=<RUN_ID>/` for audit and idempotency.

