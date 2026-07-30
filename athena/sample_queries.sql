-- Basic volume checks
SELECT COUNT(*) AS total_interactions
FROM ecommerce_pipeline.interactions_clean;

SELECT event_type, COUNT(*) AS interaction_count
FROM ecommerce_pipeline.interactions_clean
GROUP BY event_type
ORDER BY interaction_count DESC;

SELECT COUNT(DISTINCT user_id) AS unique_users
FROM ecommerce_pipeline.interactions_clean;

SELECT COUNT(DISTINCT item_id) AS unique_items
FROM ecommerce_pipeline.interactions_clean;

-- Top products by supported event
SELECT item_id, COUNT(*) AS view_count
FROM ecommerce_pipeline.interactions_clean
WHERE event_type = 'view'
GROUP BY item_id
ORDER BY view_count DESC
LIMIT 10;

SELECT item_id, COUNT(*) AS add_to_cart_count
FROM ecommerce_pipeline.interactions_clean
WHERE event_type = 'add_to_cart'
GROUP BY item_id
ORDER BY add_to_cart_count DESC
LIMIT 10;

SELECT item_id, COUNT(*) AS purchase_count
FROM ecommerce_pipeline.interactions_clean
WHERE event_type = 'purchase'
GROUP BY item_id
ORDER BY purchase_count DESC
LIMIT 10;

-- Time and user activity
SELECT date(from_unixtime(event_timestamp)) AS event_date, COUNT(*) AS event_count
FROM ecommerce_pipeline.interactions_clean
GROUP BY 1
ORDER BY 1;

SELECT user_id, COUNT(*) AS interaction_count
FROM ecommerce_pipeline.interactions_clean
GROUP BY user_id
ORDER BY interaction_count DESC
LIMIT 20;

-- These four validation queries should each return zero.
SELECT COUNT(*) AS empty_user_id_count
FROM ecommerce_pipeline.interactions_clean
WHERE user_id IS NULL OR trim(user_id) = '';

SELECT COUNT(*) AS empty_item_id_count
FROM ecommerce_pipeline.interactions_clean
WHERE item_id IS NULL OR trim(item_id) = '';

SELECT COUNT(*) AS invalid_event_type_count
FROM ecommerce_pipeline.interactions_clean
WHERE event_type NOT IN ('view', 'add_to_cart', 'remove_from_cart', 'purchase');

SELECT COUNT(*) AS invalid_timestamp_count
FROM ecommerce_pipeline.interactions_clean
WHERE event_timestamp IS NULL OR event_timestamp <= 0;

-- Evidence that original system IDs remain intact.
SELECT user_id, item_id, event_type, event_timestamp
FROM ecommerce_pipeline.interactions_clean
WHERE regexp_like(user_id, '^user-[0-9]+$')
  AND regexp_like(item_id, '^prod-[0-9]+$')
LIMIT 20;

