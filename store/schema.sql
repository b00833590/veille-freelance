-- Schéma SQLite du système de veille. Idempotent.

CREATE TABLE IF NOT EXISTS offers (
    id               TEXT PRIMARY KEY,          -- = fingerprint stable
    fingerprint      TEXT NOT NULL,
    title            TEXT NOT NULL,
    company          TEXT,
    company_norm     TEXT,
    category         TEXT DEFAULT 'UNKNOWN',    -- A | B | C | UNKNOWN
    description      TEXT,
    url              TEXT,
    url_canonical    TEXT,
    sources          TEXT DEFAULT '[]',         -- JSON: [{source,url,external_id,seen_at}]
    location         TEXT,
    remote           TEXT DEFAULT 'unknown',    -- remote | hybrid | onsite | unknown
    contract_type    TEXT,
    work_time        TEXT DEFAULT 'unknown',    -- fulltime | parttime | freelance | internship | unknown
    work_time_hours  INTEGER,
    salary_raw       TEXT,
    salary_min       REAL,
    salary_max       REAL,
    skills           TEXT DEFAULT '[]',         -- JSON list
    published_at     TEXT,
    discovered_at    TEXT NOT NULL,
    last_checked_at  TEXT NOT NULL,
    score            INTEGER DEFAULT 0,
    score_breakdown  TEXT DEFAULT '{}',         -- JSON: {component: {points,max,reason}}
    llm_analysis     TEXT,                      -- JSON | NULL
    priority         INTEGER DEFAULT 3,         -- 1 | 2 | 3
    status           TEXT DEFAULT 'new',        -- new|seen|interesting|applied|obtained|ignored|excluded
    archived         INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_offers_url_canonical ON offers(url_canonical);
CREATE INDEX IF NOT EXISTS idx_offers_fingerprint   ON offers(fingerprint);
CREATE INDEX IF NOT EXISTS idx_offers_company_norm  ON offers(company_norm);
CREATE INDEX IF NOT EXISTS idx_offers_status        ON offers(status);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id    TEXT NOT NULL,
    verdict     TEXT NOT NULL,                  -- up|star|down|exclude|applied|obtained
    reason      TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (offer_id) REFERENCES offers(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_offer ON feedback(offer_id);

CREATE TABLE IF NOT EXISTS pref_weights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at    TEXT NOT NULL,
    weights        TEXT NOT NULL,               -- JSON: {component: weight}
    feedback_count INTEGER NOT NULL DEFAULT 0,
    confidence     TEXT NOT NULL DEFAULT 'low', -- low | med | high
    trigger        TEXT NOT NULL DEFAULT 'auto' -- auto | manual
);

CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    sources_ok     TEXT DEFAULT '[]',
    sources_failed TEXT DEFAULT '[]',
    n_raw          INTEGER DEFAULT 0,
    n_new          INTEGER DEFAULT 0,
    n_scored       INTEGER DEFAULT 0,
    n_llm          INTEGER DEFAULT 0,
    n_priority1    INTEGER DEFAULT 0,
    n_priority2    INTEGER DEFAULT 0,
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
