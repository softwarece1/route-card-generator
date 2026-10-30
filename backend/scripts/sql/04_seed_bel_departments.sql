-- ============================================================
-- 04_seed_bel_departments.sql
-- ============================================================
-- Connect to database "route_card" in pgAdmin, then run.
-- Safe to re-run (upsert by code). Deactivates non-BEL rows.
-- Source: BEL dept list (BG excluded). Includes plant_id (WERKS).
-- ============================================================

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

-- Verify:
-- SELECT code, name, plant_id, sort_order, is_active FROM route_card.departments ORDER BY sort_order;
