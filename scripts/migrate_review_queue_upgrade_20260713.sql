ALTER TABLE analysis_review_queue
  ADD COLUMN review_reason_code VARCHAR(32) NULL AFTER reviewed_by;
