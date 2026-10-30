-- ============================================================
-- 07_upgrade_to_current_retain_data.sql
-- ============================================================
-- PURPOSE
--   Bring an older route_card deployment up to the CURRENT app
--   schema WITHOUT dropping or rewriting existing data
--   (sessions, documents, extractions, drawings, route cards,
--   users, ops, etc.).
--
-- WHERE TO RUN
--   pgAdmin → connect to database "route_card" → Query Tool →
--   Open / run this entire file as a single script.
--   Prefer PostgreSQL 14+ (ADD COLUMN IF NOT EXISTS).
--
-- SAFE TO RE-RUN
--   Uses CREATE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
--   CREATE INDEX IF NOT EXISTS. Existing rows are kept.
--   Only BEL department upserts may refresh name/plant_id/
--   sort_order; non-BEL dept rows are deactivated (not deleted).
--   No BEGIN/COMMIT wrapper — so a mid-script error does not
--   roll back earlier successful DDL (easier to resume in pgAdmin).
--
-- COVERS
--   A) Very old offline runtime (sessions/drawings/documents/
--      extractions/route_cards/operations/inspection_chars only)
--   B) Mid deployments (users + analyze_jobs + templates, but
--      missing work_centers / IED / plant_id / link columns)
--   C) Already-current DBs (no-op)
--
-- AFTER THIS FILE
--   Optionally run 06_verify_offline_install.sql.
--   Then on the offline PC recreate backend\.venv (do NOT copy
--   .venv) and install from backend\offline_packages.
--   Starting the backend also re-applies the same DDL via
--   migrations_route_card.py.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS route_card;

-- =====================================================================
-- 1) Auth / users (required by current app; old runtime had none)
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.users (
    id SERIAL PRIMARY KEY,
    emp_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    dept VARCHAR(128) NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'engineer',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE route_card.users
    ADD COLUMN IF NOT EXISTS dept VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE route_card.users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS route_card.password_history (
    id SERIAL PRIMARY KEY,
    "user" INTEGER NOT NULL
        REFERENCES route_card.users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_password_history_user_created
    ON route_card.password_history ("user", created_at DESC);

-- =====================================================================
-- 2) Core upload / extraction tables (retain all existing rows)
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.sessions (
    id SERIAL PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE route_card.sessions
    ADD COLUMN IF NOT EXISTS "user" INTEGER
    REFERENCES route_card.users(id)
    ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS route_card.drawings (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    content_type VARCHAR(128),
    object_path TEXT NOT NULL,
    storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    pages INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    drawing_type VARCHAR(32) DEFAULT 'unknown',
    uploaded_by VARCHAR(128),
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE route_card.drawings
    ADD COLUMN IF NOT EXISTS session INTEGER
    REFERENCES route_card.sessions(id)
    ON DELETE SET NULL;

ALTER TABLE route_card.drawings
    ADD COLUMN IF NOT EXISTS "user" INTEGER
    REFERENCES route_card.users(id)
    ON DELETE SET NULL;

-- Session documents hold GA / PL / WL bytes metadata + extraction JSONB
CREATE TABLE IF NOT EXISTS route_card.documents (
    id SERIAL PRIMARY KEY,
    session INTEGER NOT NULL
        REFERENCES route_card.sessions(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    content_type VARCHAR(128),
    object_path TEXT NOT NULL,
    storage_backend VARCHAR(64) NOT NULL DEFAULT 'minio',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    extraction JSONB,
    warnings JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_card.extractions (
    id SERIAL PRIMARY KEY,
    drawing INTEGER NOT NULL
        REFERENCES route_card.drawings(id) ON DELETE CASCADE,
    title_block JSONB,
    revisions JSONB,
    bom_items JSONB,
    notes JSONB,
    torque_specs JSONB,
    dimensions JSONB,
    "references" JSONB,
    warnings JSONB,
    raw_text TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_card.route_cards (
    id SERIAL PRIMARY KEY,
    drawing INTEGER NOT NULL
        REFERENCES route_card.drawings(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    part_info JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- IED workflow columns (nullable — existing cards stay draft / unchanged)
ALTER TABLE route_card.route_cards
    ADD COLUMN IF NOT EXISTS ied_shared_at TIMESTAMP;
ALTER TABLE route_card.route_cards
    ADD COLUMN IF NOT EXISTS ied_shared_by_id INTEGER;
ALTER TABLE route_card.route_cards
    ADD COLUMN IF NOT EXISTS ied_completed_at TIMESTAMP;
ALTER TABLE route_card.route_cards
    ADD COLUMN IF NOT EXISTS ied_completed_by_id INTEGER;

CREATE TABLE IF NOT EXISTS route_card.operations (
    id SERIAL PRIMARY KEY,
    route_card INTEGER NOT NULL
        REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
    op_no INTEGER NOT NULL,
    operation VARCHAR(512) NOT NULL,
    work_centre VARCHAR(128),
    machine VARCHAR(128),
    tool VARCHAR(256),
    items_used JSONB,
    torque_spec VARCHAR(256),
    reference VARCHAR(512),
    setup VARCHAR(32),
    time VARCHAR(64),
    inspection VARCHAR(256),
    instruction_text TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'Planned'
);

-- WC / machine link columns used by current route generator / review
ALTER TABLE route_card.operations
    ADD COLUMN IF NOT EXISTS work_centre_id INTEGER;
ALTER TABLE route_card.operations
    ADD COLUMN IF NOT EXISTS machine_id INTEGER;
ALTER TABLE route_card.operations
    ADD COLUMN IF NOT EXISTS link_status VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE route_card.operations
    ADD COLUMN IF NOT EXISTS link_confidence DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS route_card.inspection_chars (
    id SERIAL PRIMARY KEY,
    route_card INTEGER NOT NULL
        REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
    characteristic VARCHAR(512) NOT NULL,
    nominal VARCHAR(256),
    tolerance VARCHAR(256),
    method VARCHAR(256),
    frequency VARCHAR(128),
    criticality VARCHAR(64),
    source VARCHAR(256)
);

-- =====================================================================
-- 3) Departments + BEL master (upsert; keep custom rows deactivated)
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.departments (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE route_card.departments
    ADD COLUMN IF NOT EXISTS plant_id VARCHAR(32) NOT NULL DEFAULT '';

INSERT INTO route_card.departments (code, name, plant_id, is_active, sort_order) VALUES
    ('MR',          'MR',                    '1100', TRUE, 10),
    ('MS',          'MS',                    '1200', TRUE, 20),
    ('ARMS_AMMO',   'Arms & Ammunition',     '1300', TRUE, 30),
    ('NS1',         'NS1',                   '1400', TRUE, 40),
    ('NS2',         'NS2',                   '1500', TRUE, 50),
    ('ADSN',        'ADSN',                  '1600', TRUE, 60),
    ('MCE_NCS',     'MCE/NCS',               '1700', TRUE, 70),
    ('NWCS',        'NWCS',                  '1800', TRUE, 80),
    ('SC',          'SC',                    '1900', TRUE, 90),
    ('US',          'US',                    '2000', TRUE, 100),
    ('HLS',         'HLS',                   '2100', TRUE, 110),
    ('EW_A',        'EW&A',                  '2200', TRUE, 120),
    ('SEEKERS',     'Seekers (RF & IR)',     '2300', TRUE, 130),
    ('EM',          'EM',                    '2400', TRUE, 140),
    ('COMPONENTS',  'Components',            '2500', TRUE, 150),
    ('SOFTWARE',    'Software',              '2600', TRUE, 160),
    ('AF',          'A&F',                   '2700', TRUE, 170),
    ('ES',          'ES',                    '2800', TRUE, 180),
    ('CSG',         'CSG',                   '2900', TRUE, 190),
    ('CUSTOMER',    'Customer',              '3000', TRUE, 200)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    plant_id = EXCLUDED.plant_id,
    is_active = TRUE,
    sort_order = EXCLUDED.sort_order;

UPDATE route_card.departments
SET is_active = FALSE
WHERE code NOT IN (
    'MR', 'MS', 'ARMS_AMMO', 'NS1', 'NS2', 'ADSN', 'MCE_NCS', 'NWCS',
    'SC', 'US', 'HLS', 'EW_A', 'SEEKERS', 'EM', 'COMPONENTS',
    'SOFTWARE', 'AF', 'ES', 'CSG', 'CUSTOMER'
);

-- =====================================================================
-- 4) Operation templates
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.operation_templates (
    id SERIAL PRIMARY KEY,
    dept VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    placement VARCHAR(16) NOT NULL DEFAULT 'any',
    created_by INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE route_card.operation_templates
    ADD COLUMN IF NOT EXISTS copied_from_id INTEGER NULL;

CREATE INDEX IF NOT EXISTS ix_operation_templates_dept_active
    ON route_card.operation_templates (dept, is_active);

CREATE INDEX IF NOT EXISTS ix_operation_templates_copied_from
    ON route_card.operation_templates (dept, copied_from_id)
    WHERE copied_from_id IS NOT NULL AND is_active = TRUE;

CREATE TABLE IF NOT EXISTS route_card.operation_template_steps (
    id SERIAL PRIMARY KEY,
    template INTEGER NOT NULL
        REFERENCES route_card.operation_templates(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    operation VARCHAR(512) NOT NULL,
    work_centre VARCHAR(128) NOT NULL DEFAULT '',
    setup VARCHAR(32) NOT NULL DEFAULT '',
    time VARCHAR(64) NOT NULL DEFAULT '',
    instruction_text TEXT,
    inspection VARCHAR(256) NOT NULL DEFAULT '',
    machine VARCHAR(128) NOT NULL DEFAULT '',
    tool VARCHAR(256) NOT NULL DEFAULT '',
    generates_output_serial BOOLEAN NOT NULL DEFAULT FALSE,
    requires_input_material BOOLEAN NOT NULL DEFAULT FALSE,
    manual_operation BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS ix_operation_template_steps_template
    ON route_card.operation_template_steps (template, sort_order);

-- =====================================================================
-- 5) Analyze jobs / review / audit / notifications / favorites / rules
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.analyze_jobs (
    id SERIAL PRIMARY KEY,
    session INTEGER NOT NULL
        REFERENCES route_card.sessions(id) ON DELETE CASCADE,
    "user" INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error_message TEXT,
    vlm_page_indexes JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    finished_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_analyze_jobs_status_created
    ON route_card.analyze_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS route_card.review_flags (
    id SERIAL PRIMARY KEY,
    session INTEGER
        REFERENCES route_card.sessions(id) ON DELETE CASCADE,
    route_card INTEGER
        REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
    "user" INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    kind VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'medium',
    message TEXT NOT NULL,
    source VARCHAR(128) NOT NULL DEFAULT '',
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMP WITHOUT TIME ZONE,
    resolved_by VARCHAR(128),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_review_flags_route_resolved
    ON route_card.review_flags (route_card, resolved);

CREATE TABLE IF NOT EXISTS route_card.audit_events (
    id SERIAL PRIMARY KEY,
    route_card INTEGER
        REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
    session INTEGER,
    "user" INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    action VARCHAR(64) NOT NULL,
    detail JSONB,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_card.notifications (
    id SERIAL PRIMARY KEY,
    "user" INTEGER NOT NULL
        REFERENCES route_card.users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link VARCHAR(512) NOT NULL DEFAULT '',
    read_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_notifications_user_created
    ON route_card.notifications ("user", created_at DESC);

CREATE TABLE IF NOT EXISTS route_card.user_favorites (
    id SERIAL PRIMARY KEY,
    "user" INTEGER NOT NULL
        REFERENCES route_card.users(id) ON DELETE CASCADE,
    part_number VARCHAR(128) NOT NULL DEFAULT '',
    label VARCHAR(255) NOT NULL DEFAULT '',
    session_id INTEGER,
    route_card_id INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS route_card.dept_rules (
    id SERIAL PRIMARY KEY,
    dept VARCHAR(128) NOT NULL UNIQUE,
    rules JSONB,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS route_card.few_shot_examples (
    id SERIAL PRIMARY KEY,
    dept VARCHAR(128) NOT NULL,
    doc_type VARCHAR(32) NOT NULL DEFAULT 'drawing',
    title VARCHAR(255) NOT NULL,
    input_excerpt TEXT,
    output_excerpt TEXT NOT NULL,
    created_by INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- =====================================================================
-- 6) Work centres + machines (current linking model)
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.work_centers (
    id SERIAL PRIMARY KEY,
    dept VARCHAR(128) NOT NULL DEFAULT '',
    code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    mode VARCHAR(32) NOT NULL DEFAULT 'hybrid',
    is_shared BOOLEAN NOT NULL DEFAULT FALSE,
    plant VARCHAR(128) NOT NULL DEFAULT '',
    sap_code VARCHAR(128) NOT NULL DEFAULT '',
    capability_tags JSONB,
    match_keywords JSONB,
    default_tool VARCHAR(256) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_shared_code
    ON route_card.work_centers (code)
    WHERE is_shared = TRUE AND is_active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_dept_code
    ON route_card.work_centers (dept, code)
    WHERE is_shared = FALSE AND is_active = TRUE;

CREATE TABLE IF NOT EXISTS route_card.machines (
    id SERIAL PRIMARY KEY,
    plant VARCHAR(128) NOT NULL DEFAULT '',
    work_centre VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS work_center INTEGER
        REFERENCES route_card.work_centers(id) ON DELETE SET NULL;
ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS dept VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS code VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS sap_code VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS capability_tags JSONB;
ALTER TABLE route_card.machines
    ADD COLUMN IF NOT EXISTS is_manual_placeholder BOOLEAN NOT NULL DEFAULT FALSE;

-- =====================================================================
-- 7) Route remarks (Pony column names: route_card / "user")
-- =====================================================================
CREATE TABLE IF NOT EXISTS route_card.route_remarks (
    id SERIAL PRIMARY KEY,
    route_card INTEGER NOT NULL
        REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
    "user" INTEGER
        REFERENCES route_card.users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Repair early drafts that used route_card_id / user_id
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'route_card'
      AND table_name = 'route_remarks'
      AND column_name = 'route_card_id'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'route_card'
      AND table_name = 'route_remarks'
      AND column_name = 'route_card'
  ) THEN
    ALTER TABLE route_card.route_remarks
      RENAME COLUMN route_card_id TO route_card;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'route_card'
      AND table_name = 'route_remarks'
      AND column_name = 'user_id'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'route_card'
      AND table_name = 'route_remarks'
      AND column_name = 'user'
  ) THEN
    ALTER TABLE route_card.route_remarks
      RENAME COLUMN user_id TO "user";
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_route_remarks_card
    ON route_card.route_remarks (route_card, created_at);

-- =====================================================================
-- 8) Grants (harmless if already granted)
-- =====================================================================
GRANT ALL ON SCHEMA route_card TO route_card;
GRANT ALL ON ALL TABLES IN SCHEMA route_card TO route_card;
GRANT ALL ON ALL SEQUENCES IN SCHEMA route_card TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON TABLES TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON SEQUENCES TO route_card;

-- =====================================================================
-- Quick verify (optional — run separately after upgrade)
-- =====================================================================
-- SELECT COUNT(*) AS sessions FROM route_card.sessions;
-- SELECT COUNT(*) AS documents FROM route_card.documents;
-- SELECT COUNT(*) AS extractions FROM route_card.extractions;
-- SELECT COUNT(*) AS route_cards FROM route_card.route_cards;
-- SELECT column_name FROM information_schema.columns
--   WHERE table_schema='route_card' AND table_name='operations'
--     AND column_name IN ('work_centre_id','machine_id','link_status');
-- SELECT column_name FROM information_schema.columns
--   WHERE table_schema='route_card' AND table_name='departments'
--     AND column_name='plant_id';
