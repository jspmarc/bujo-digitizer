-- initial schema
-- depends:

CREATE TABLE IF NOT EXISTS to_review_digitize_result (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	paperless_doc_id INTEGER NOT NULL,
	doc_title TEXT NOT NULL,
	doc_created TEXT NOT NULL DEFAULT '',
	parse_result TEXT,
	bbox_elements TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS to_review_digitize_page (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	result_id INTEGER NOT NULL,
	page_index INTEGER NOT NULL,
	image BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS digitize_job (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	paperless_doc_id INTEGER NOT NULL,
	doc_title TEXT NOT NULL,
	doc_created TEXT NOT NULL DEFAULT '',
	status TEXT NOT NULL DEFAULT 'pending',
	attempts INTEGER NOT NULL DEFAULT 0,
	max_attempts INTEGER NOT NULL DEFAULT 3,
	last_error TEXT,
	created_at TEXT NOT NULL DEFAULT (datetime('now')),
	updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS digitize_job_active_doc ON digitize_job (paperless_doc_id)
	WHERE status IN ('pending', 'running');
