-- ===== Meme Alpha schema (full) =====

-- calls that were posted to Discord
CREATE TABLE IF NOT EXISTS calls (
  id           BIGSERIAL PRIMARY KEY,
  called_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  token_mint   TEXT,
  pair_address TEXT UNIQUE,
  score        NUMERIC,
  liq_usd      NUMERIC,
  fdv_usd      NUMERIC,
  pchg_5m      NUMERIC,
  pchg_1h      NUMERIC,
  meta         JSONB
);
CREATE INDEX IF NOT EXISTS idx_calls_time ON calls(called_at DESC);

-- outcomes checked at +15m and +1h
CREATE TABLE IF NOT EXISTS call_outcomes (
  id             BIGSERIAL PRIMARY KEY,
  call_id        BIGINT REFERENCES calls(id) ON DELETE CASCADE,
  pair_address   TEXT,
  token_mint     TEXT,
  called_at      TIMESTAMPTZ NOT NULL,
  price_at_call  DOUBLE PRECISION,
  due_15m        TIMESTAMPTZ,
  due_1h         TIMESTAMPTZ,
  price_15m      DOUBLE PRECISION,
  price_1h       DOUBLE PRECISION,
  gain_15m       DOUBLE PRECISION,
  gain_1h        DOUBLE PRECISION,
  win_15m        BOOLEAN,
  win_1h         BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_outcomes_due15 ON call_outcomes(due_15m) WHERE price_15m IS NULL;
CREATE INDEX IF NOT EXISTS idx_outcomes_due1h ON call_outcomes(due_1h) WHERE price_1h IS NULL;

-- tiny scan log (auto-pruned by code)
CREATE TABLE IF NOT EXISTS scan_events (
  id           BIGSERIAL PRIMARY KEY,
  seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage        TEXT NOT NULL,                -- 'base_reject' | 'qualified' | 'posted'
  pair_address TEXT,
  chain        TEXT,
  dex          TEXT,
  symbol       TEXT,
  score        NUMERIC,
  reasons      JSONB
);
CREATE INDEX IF NOT EXISTS idx_scan_events_seen  ON scan_events(seen_at);
CREATE INDEX IF NOT EXISTS idx_scan_events_stage ON scan_events(stage);

-- lifecycle of tokens we discover (prevents re-checking garbage forever)
-- stages: 0=never_recheck, 1=watch, 2=qualified, 3=posted, 4=dead
CREATE TABLE IF NOT EXISTS token_lifecycle (
  pair_address TEXT PRIMARY KEY,
  symbol       TEXT,
  token_mint   TEXT,
  first_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage        INT NOT NULL DEFAULT 1,
  notes        TEXT,
  meta         JSONB
);
CREATE INDEX IF NOT EXISTS idx_token_stage ON token_lifecycle(stage);
CREATE INDEX IF NOT EXISTS idx_token_last_checked ON token_lifecycle(last_checked DESC);

-- hot keywords (trends/news). scores decay over time in trends.py
CREATE TABLE IF NOT EXISTS hot_keywords (
  term        TEXT PRIMARY KEY,
  score       NUMERIC NOT NULL,     -- 0..100
  last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);
