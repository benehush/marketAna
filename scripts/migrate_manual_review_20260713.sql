ALTER TABLE analysis_review_queue
  ADD COLUMN reviewed_by VARCHAR(128) NULL AFTER status,
  ADD COLUMN review_reason_code VARCHAR(32) NULL AFTER reviewed_by,
  ADD COLUMN review_note TEXT NULL AFTER review_reason_code,
  ADD COLUMN reviewed_at DATETIME NULL AFTER review_note;
