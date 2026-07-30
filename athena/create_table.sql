-- Replace <BUCKET_NAME> before running this statement.
CREATE EXTERNAL TABLE IF NOT EXISTS ecommerce_pipeline.interactions_clean (
  user_id string,
  item_id string,
  event_type string,
  event_timestamp bigint
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
  'separatorChar' = ',',
  'quoteChar' = '"',
  'escapeChar' = '\\'
)
STORED AS TEXTFILE
LOCATION 's3://<BUCKET_NAME>/processed/latest/'
TBLPROPERTIES (
  'skip.header.line.count' = '1'
);

