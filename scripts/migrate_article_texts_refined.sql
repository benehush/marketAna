-- Add user-facing refined text fields to article_texts.
-- MySQL 8.x. Run after backing up the database.

ALTER TABLE article_texts
  ADD COLUMN refined_text LONGTEXT NULL AFTER cleaned_text,
  ADD COLUMN refined_length INT NOT NULL DEFAULT 0 AFTER cleaned_length;
