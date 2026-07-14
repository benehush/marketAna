-- Product catalog identity and alias review loop.
-- MySQL 8.x. Back up the database and run this migration once.

ALTER TABLE article_product_segments
  ADD COLUMN product_key VARCHAR(64) NOT NULL DEFAULT '' AFTER product,
  ADD COLUMN raw_product_name VARCHAR(255) NULL AFTER product_key,
  ADD COLUMN resolution_method VARCHAR(32) NOT NULL DEFAULT 'unknown' AFTER raw_product_name,
  ADD COLUMN resolution_confidence DOUBLE NOT NULL DEFAULT 0 AFTER resolution_method,
  ADD KEY ix_article_product_segments_product_key (product_key);

ALTER TABLE analysis_results
  ADD COLUMN product_key VARCHAR(64) NOT NULL DEFAULT '' AFTER product,
  ADD KEY ix_analysis_results_product_key (product_key);

ALTER TABLE manual_confirmations
  ADD COLUMN original_product_key VARCHAR(64) NULL AFTER original_product,
  ADD COLUMN confirmed_product_key VARCHAR(64) NULL AFTER confirmed_product;

CREATE TABLE product_resolutions (
  id INT NOT NULL AUTO_INCREMENT,
  article_id INT NOT NULL,
  block_fingerprint VARCHAR(64) NOT NULL,
  segment_index INT NOT NULL DEFAULT 0,
  raw_name VARCHAR(255) NOT NULL DEFAULT '',
  normalized_raw_name VARCHAR(255) NOT NULL DEFAULT '',
  excerpt TEXT NULL,
  start_char INT NULL,
  end_char INT NULL,
  suggested_product_key VARCHAR(64) NULL,
  resolved_product_key VARCHAR(64) NULL,
  confidence DOUBLE NOT NULL DEFAULT 0,
  method VARCHAR(32) NOT NULL DEFAULT 'unknown',
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  reviewed_by VARCHAR(128) NULL,
  review_note TEXT NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_product_resolution_block (article_id, block_fingerprint),
  KEY ix_product_resolutions_article_id (article_id),
  KEY ix_product_resolutions_normalized_raw_name (normalized_raw_name),
  KEY ix_product_resolutions_status_created (status, created_at),
  CONSTRAINT fk_product_resolutions_article
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);

CREATE TABLE product_aliases (
  id INT NOT NULL AUTO_INCREMENT,
  alias VARCHAR(255) NOT NULL,
  normalized_alias VARCHAR(255) NOT NULL,
  product_key VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  source_resolution_id INT NULL,
  occurrence_count INT NOT NULL DEFAULT 1,
  confidence DOUBLE NOT NULL DEFAULT 0,
  reviewed_by VARCHAR(128) NULL,
  review_note TEXT NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_product_alias_target (normalized_alias, product_key),
  KEY ix_product_aliases_normalized_alias (normalized_alias),
  KEY ix_product_aliases_product_key (product_key),
  KEY ix_product_aliases_status_created (status, created_at),
  CONSTRAINT fk_product_aliases_resolution
    FOREIGN KEY (source_resolution_id) REFERENCES product_resolutions(id) ON DELETE SET NULL
);

-- Backfill only unambiguous legacy display names. Generic financial products
-- intentionally remain aggregate keys and are never expanded into children.
UPDATE article_product_segments
SET product_key = CASE product
  WHEN '沪铜' THEN 'SHFE.CU' WHEN '沪铝' THEN 'SHFE.AL'
  WHEN '沪锌' THEN 'SHFE.ZN' WHEN '沪铅' THEN 'SHFE.PB'
  WHEN '沪镍' THEN 'SHFE.NI' WHEN '沪锡' THEN 'SHFE.SN'
  WHEN '黄金' THEN 'SHFE.AU' WHEN '白银' THEN 'SHFE.AG'
  WHEN '螺纹钢' THEN 'SHFE.RB' WHEN '热轧卷板' THEN 'SHFE.HC'
  WHEN '不锈钢' THEN 'SHFE.SS' WHEN '氧化铝' THEN 'SHFE.AO'
  WHEN '燃料油' THEN 'SHFE.FU' WHEN '低硫燃料油' THEN 'INE.LU'
  WHEN '原油' THEN 'INE.SC' WHEN '集运指数（欧线）' THEN 'INE.EC'
  WHEN '豆粕' THEN 'DCE.M' WHEN '豆油' THEN 'DCE.Y'
  WHEN '棕榈油' THEN 'DCE.P' WHEN '玉米' THEN 'DCE.C'
  WHEN '玉米淀粉' THEN 'DCE.CS' WHEN '铁矿石' THEN 'DCE.I'
  WHEN '焦炭' THEN 'DCE.J' WHEN '焦煤' THEN 'DCE.JM'
  WHEN '乙二醇' THEN 'DCE.EG' WHEN '苯乙烯' THEN 'DCE.EB'
  WHEN '液化气' THEN 'DCE.PG' WHEN 'LLDPE' THEN 'DCE.L'
  WHEN 'PVC' THEN 'DCE.V' WHEN 'PP' THEN 'DCE.PP'
  WHEN '白糖' THEN 'CZCE.SR' WHEN '棉花' THEN 'CZCE.CF'
  WHEN '菜粕' THEN 'CZCE.RM' WHEN '菜油' THEN 'CZCE.OI'
  WHEN 'PTA' THEN 'CZCE.TA' WHEN '甲醇' THEN 'CZCE.MA'
  WHEN '玻璃' THEN 'CZCE.FG' WHEN '纯碱' THEN 'CZCE.SA'
  WHEN '尿素' THEN 'CZCE.UR' WHEN '烧碱' THEN 'CZCE.SH'
  WHEN '碳酸锂' THEN 'GFEX.LC' WHEN '工业硅' THEN 'GFEX.SI'
  WHEN '股指' THEN 'GROUP.CFFEX.INDEX' WHEN '国债' THEN 'GROUP.CFFEX.BOND'
  ELSE product_key END
WHERE product_key = '';

UPDATE analysis_results a
JOIN article_product_segments s
  ON s.article_id = a.article_id AND s.product = a.product
SET a.product_key = s.product_key
WHERE a.product_key = '' AND s.product_key <> '';

UPDATE analysis_results
SET product_key = CASE product
  WHEN '股指' THEN 'GROUP.CFFEX.INDEX'
  WHEN '国债' THEN 'GROUP.CFFEX.BOND'
  ELSE product_key END
WHERE product_key = '';
