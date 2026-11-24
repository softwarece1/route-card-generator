-- ============================================================
-- 04_seed_bel_sbus.sql
-- ============================================================
-- Connect to database "route_card" in pgAdmin, then run.
-- Safe to re-run (upsert by code). Deactivates non-BEL rows.
-- Source: BEL SBU list (BG excluded). plant_id left blank until
-- SBU → SAP plant mapping is provided.
-- ============================================================

ALTER TABLE route_card.sbus
    ADD COLUMN IF NOT EXISTS plant_id VARCHAR(32) NOT NULL DEFAULT '';

INSERT INTO route_card.sbus (code, name, plant_id, is_active, sort_order) VALUES
    ('MR',          'MR',                    '', TRUE, 10),
    ('MS',          'MS',                    '', TRUE, 20),
    ('ARMS_AMMO',   'Arms & Ammunition',     '', TRUE, 30),
    ('NS1',         'NS1',                   '', TRUE, 40),
    ('NS2',         'NS2',                   '', TRUE, 50),
    ('ADSN',        'ADSN',                  '', TRUE, 60),
    ('MCE_NCS',     'MCE/NCS',               '', TRUE, 70),
    ('NWCS',        'NWCS',                  '', TRUE, 80),
    ('SC',          'SC',                    '', TRUE, 90),
    ('US',          'US',                    '', TRUE, 100),
    ('HLS',         'HLS',                   '', TRUE, 110),
    ('EW_A',        'EW&A',                  '', TRUE, 120),
    ('SEEKERS',     'Seekers (RF & IR)',     '', TRUE, 130),
    ('EM',          'EM',                    '', TRUE, 140),
    ('COMPONENTS',  'Components',            '', TRUE, 150),
    ('SOFTWARE',    'Software',              '', TRUE, 160),
    ('AF',          'A&F',                   '', TRUE, 170),
    ('ES',          'ES',                    '', TRUE, 180),
    ('CSG',         'CSG',                   '', TRUE, 190),
    ('CUSTOMER',    'Customer',              '', TRUE, 200)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    is_active = TRUE,
    sort_order = EXCLUDED.sort_order;

-- Clear legacy dummy plant codes (1100–3000)
UPDATE route_card.sbus
SET plant_id = ''
WHERE plant_id IN (
    '1100', '1200', '1300', '1400', '1500', '1600', '1700', '1800',
    '1900', '2000', '2100', '2200', '2300', '2400', '2500', '2600',
    '2700', '2800', '2900', '3000'
);

UPDATE route_card.sbus
SET is_active = FALSE
WHERE code NOT IN (
    'MR', 'MS', 'ARMS_AMMO', 'NS1', 'NS2', 'ADSN', 'MCE_NCS', 'NWCS',
    'SC', 'US', 'HLS', 'EW_A', 'SEEKERS', 'EM', 'COMPONENTS',
    'SOFTWARE', 'AF', 'ES', 'CSG', 'CUSTOMER'
);

-- Verify:
-- SELECT code, name, plant_id, sort_order, is_active FROM route_card.sbus ORDER BY sort_order;
