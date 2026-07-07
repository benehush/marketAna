-- Upgrade analysis_results from one result per article to multiple product/contract results.
-- MySQL 8.x. Run after backing up the database.

ALTER TABLE analysis_results
  DROP INDEX uq_analysis_results_article_id,
  ADD COLUMN contract VARCHAR(64) NULL AFTER product,
  ADD COLUMN contract_key VARCHAR(64) NOT NULL DEFAULT '' AFTER contract,
  ADD COLUMN is_primary TINYINT(1) NOT NULL DEFAULT 0 AFTER need_manual_review,
  ADD COLUMN model_name VARCHAR(128) NULL AFTER is_primary,
  ADD COLUMN llm_duration_ms INT NULL AFTER model_name,
  ADD COLUMN llm_retry_count INT NULL AFTER llm_duration_ms,
  ADD COLUMN llm_error_msg TEXT NULL AFTER llm_retry_count,
  ADD UNIQUE KEY uq_analysis_results_article_product_contract (article_id, product, contract_key);

UPDATE analysis_results
SET is_primary = 1
WHERE id IN (
  SELECT id FROM (
    SELECT MIN(id) AS id
    FROM analysis_results
    GROUP BY article_id
  ) AS primary_rows
);
