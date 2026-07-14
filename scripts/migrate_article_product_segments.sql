-- Add persisted per-product text segments for article evidence display.
-- MySQL 8.x. Run after backing up the database.

CREATE TABLE IF NOT EXISTS article_product_segments (
  id INT NOT NULL AUTO_INCREMENT,
  article_id INT NOT NULL,
  product VARCHAR(128) NOT NULL,
  contract VARCHAR(64) NULL,
  contract_key VARCHAR(64) NOT NULL DEFAULT '',
  segment_index INT NOT NULL DEFAULT 0,
  section_type VARCHAR(32) NOT NULL DEFAULT 'core',
  heading VARCHAR(255) NULL,
  cleaned_text LONGTEXT NULL,
  refined_text LONGTEXT NULL,
  cleaned_length INT NOT NULL DEFAULT 0,
  refined_length INT NOT NULL DEFAULT 0,
  start_char INT NULL,
  end_char INT NULL,
  confidence DOUBLE NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_article_product_segments_scope (
    article_id,
    product,
    contract_key,
    section_type,
    segment_index
  ),
  KEY ix_article_product_segments_article_id (article_id),
  KEY ix_article_product_segments_product (article_id, product, contract_key),
  KEY ix_article_product_segments_section (article_id, section_type),
  CONSTRAINT fk_article_product_segments_article_id
    FOREIGN KEY (article_id) REFERENCES articles(id)
    ON DELETE CASCADE
);
