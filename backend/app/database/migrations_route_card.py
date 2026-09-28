"""Route-card schema migrations — sessions / documents / drawings.session column."""

import psycopg2

from ..config.settings import settings


def run_migrations():
    conn = psycopg2.connect(
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
    )
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS route_card;")

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS dept VARCHAR(128) NOT NULL DEFAULT '';
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.sessions (
                id SERIAL PRIMARY KEY,
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.sessions
            ADD COLUMN IF NOT EXISTS "user" INTEGER
            REFERENCES route_card.users(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.drawings
            ADD COLUMN IF NOT EXISTS session INTEGER
            REFERENCES route_card.sessions(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.drawings
            ADD COLUMN IF NOT EXISTS "user" INTEGER
            REFERENCES route_card.users(id)
            ON DELETE SET NULL;
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.route_cards (
                id SERIAL PRIMARY KEY,
                drawing INTEGER NOT NULL
                    REFERENCES route_card.drawings(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL DEFAULT 'draft',
                part_info JSONB,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.departments (
                id SERIAL PRIMARY KEY,
                code VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_templates_dept_active
            ON route_card.operation_templates (dept, is_active);
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_template_steps_template
            ON route_card.operation_template_steps (template, sort_order);
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.operation_templates
            ADD COLUMN IF NOT EXISTS copied_from_id INTEGER NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_operation_templates_copied_from
            ON route_card.operation_templates (dept, copied_from_id)
            WHERE copied_from_id IS NOT NULL AND is_active = TRUE;
            """
        )

        print("route_card migrations applied")

        # Seed / upsert BEL department master (safe to re-run; BG excluded)
        bel_departments = [
            ("MR", "MR", 10),
            ("MS", "MS", 20),
            ("ARMS_AMMO", "Arms & Ammunition", 30),
            ("NS1", "NS1", 40),
            ("NS2", "NS2", 50),
            ("ADSN", "ADSN", 60),
            ("MCE_NCS", "MCE/NCS", 70),
            ("NWCS", "NWCS", 80),
            ("SC", "SC", 90),
            ("US", "US", 100),
            ("HLS", "HLS", 110),
            ("EW_A", "EW&A", 120),
            ("SEEKERS", "Seekers (RF & IR)", 130),
            ("EM", "EM", 140),
            ("COMPONENTS", "Components", 150),
            ("SOFTWARE", "Software", 160),
            ("AF", "A&F", 170),
            ("ES", "ES", 180),
            ("CSG", "CSG", 190),
            ("CUSTOMER", "Customer", 200),
        ]
        bel_codes = [c for c, _, _ in bel_departments]
        for code, name, sort_order in bel_departments:
            cursor.execute(
                """
                INSERT INTO route_card.departments (code, name, is_active, sort_order)
                VALUES (%s, %s, TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (code, name, sort_order),
            )
        # Hide any previously seeded non-BEL rows
        cursor.execute(
            """
            UPDATE route_card.departments
            SET is_active = FALSE
            WHERE code <> ALL(%s);
            """,
            (bel_codes,),
        )
        print("upserted BEL route_card.departments master")

        # Seed default admin if no users exist
        cursor.execute("SELECT COUNT(*) FROM route_card.users;")
        count = cursor.fetchone()[0]
        if count == 0:
            from app.security import hash_password

            cursor.execute(
                """
                INSERT INTO route_card.users (emp_id, name, dept, password_hash, role, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE);
                """,
                ("admin", "Administrator", "Software", hash_password("admin123"), "admin"),
            )
            print("seeded default admin user (empId=admin / admin123)")
    finally:
        cursor.close()
        conn.close()
