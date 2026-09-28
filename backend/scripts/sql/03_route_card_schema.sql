-- ============================================================
-- 03_route_card_schema.sql
-- ============================================================
-- Offline PC / pgAdmin: connect Query Tool to database "route_card"
-- then run this file (safe to re-run).
--
-- Creates schema + tables used by auth, signup, departments,
-- upload sessions, extractions / history, route cards.
--
-- Run order on a fresh offline DB:
--   01_create_database.sql      (as postgres)
--   setup_pgadmin.sql           (role)
--   setup_pgadmin_grants.sql    (on route_card DB)
--   03_route_card_schema.sql    ← this file
--   04_seed_bel_departments.sql
--   05_seed_default_admin.sql
--
-- Note: starting the backend also applies the same DDL via
-- migrations_route_card.py — these scripts are for manual/offline apply.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS route_card;

-- ---------- Users (login / signup / history ownership) ----------
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

-- ---------- Department master (signup dropdown) ----------
CREATE TABLE IF NOT EXISTS route_card.departments (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- ---------- Sessions (upload workspace + history rows) ----------
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

-- ---------- Drawings ----------
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

-- ---------- Session documents (GA / PL / WL file metadata) ----------
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

-- ---------- Extractions (title block / BOM / notes — history OARC) ----------
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

-- ---------- Route cards + ops + inspection (history detail) ----------
CREATE TABLE IF NOT EXISTS route_card.route_cards (
    id SERIAL PRIMARY KEY,
    drawing INTEGER NOT NULL
        REFERENCES route_card.drawings(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    part_info JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

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

-- ---------- Department operation template packs ----------
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

CREATE INDEX IF NOT EXISTS ix_operation_templates_dept_active
    ON route_card.operation_templates (dept, is_active);

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

-- Grants (harmless if already granted)
GRANT ALL ON SCHEMA route_card TO route_card;
GRANT ALL ON ALL TABLES IN SCHEMA route_card TO route_card;
GRANT ALL ON ALL SEQUENCES IN SCHEMA route_card TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON TABLES TO route_card;
ALTER DEFAULT PRIVILEGES IN SCHEMA route_card GRANT ALL ON SEQUENCES TO route_card;
