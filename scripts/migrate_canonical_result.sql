-- Canonical pipeline persistence migration for MySQL 8.x.
-- Run after backing up the database.

ALTER TABLE analysis_results
  ADD COLUMN evidence_json JSON NULL AFTER need_manual_review;

ALTER TABLE analysis_results
  DROP INDEX uq_analysis_results_article_product_contract,
  ADD UNIQUE KEY uq_analysis_results_article_product_contract
    (article_id, product_key, contract_key);

CREATE TABLE IF NOT EXISTS analysis_review_queue (
  id INT NOT NULL AUTO_INCREMENT,
  article_id INT NOT NULL,
  item_key VARCHAR(128) NOT NULL,
  product_key VARCHAR(64) NULL,
  product VARCHAR(128) NULL,
  reason VARCHAR(128) NOT NULL,
  evidence_json JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_analysis_review_queue_item (article_id, item_key),
  KEY ix_analysis_review_queue_status_created (status, created_at),
  CONSTRAINT fk_analysis_review_queue_article FOREIGN KEY (article_id)
    REFERENCES articles(id) ON DELETE CASCADE
);
