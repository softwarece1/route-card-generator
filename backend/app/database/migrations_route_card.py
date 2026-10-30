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

        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_analyze_jobs_status_created
            ON route_card.analyze_jobs (status, created_at);
            """
        )

        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_review_flags_route_resolved
            ON route_card.review_flags (route_card, resolved);
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_notifications_user_created
            ON route_card.notifications ("user", created_at DESC);
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.dept_rules (
                id SERIAL PRIMARY KEY,
                dept VARCHAR(128) NOT NULL UNIQUE,
                rules JSONB,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_by VARCHAR(128)
            );
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.password_history (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_password_history_user_created
            ON route_card.password_history ("user", created_at DESC);
            """
        )

        # Work centres master + machine / operation link columns
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_shared_code
            ON route_card.work_centers (code)
            WHERE is_shared = TRUE AND is_active = TRUE;
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_dept_code
            ON route_card.work_centers (dept, code)
            WHERE is_shared = FALSE AND is_active = TRUE;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS work_center INTEGER
                REFERENCES route_card.work_centers(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS dept VARCHAR(128) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS code VARCHAR(64) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS sap_code VARCHAR(128) NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS capability_tags JSONB;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.machines
            ADD COLUMN IF NOT EXISTS is_manual_placeholder BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
        for col, typ in [
            ("work_centre_id", "INTEGER"),
            ("machine_id", "INTEGER"),
            ("link_status", "VARCHAR(32) NOT NULL DEFAULT ''"),
            ("link_confidence", "DOUBLE PRECISION"),
        ]:
            cursor.execute(
                f"""
                ALTER TABLE route_card.operations
                ADD COLUMN IF NOT EXISTS {col} {typ};
                """
            )

        for col, typ in [
            ("ied_shared_at", "TIMESTAMP"),
            ("ied_shared_by_id", "INTEGER"),
            ("ied_completed_at", "TIMESTAMP"),
            ("ied_completed_by_id", "INTEGER"),
        ]:
            cursor.execute(
                f"""
                ALTER TABLE route_card.route_cards
                ADD COLUMN IF NOT EXISTS {col} {typ};
                """
            )

        # Pony maps Required(RcRouteCard) -> column "route_card" (not route_card_id)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.route_remarks (
                id SERIAL PRIMARY KEY,
                route_card INTEGER NOT NULL
                    REFERENCES route_card.route_cards(id) ON DELETE CASCADE,
                "user" INTEGER
                    REFERENCES route_card.users(id) ON DELETE SET NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """
        )
        # Repair early draft that used route_card_id / user_id
        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_route_remarks_card
            ON route_card.route_remarks (route_card, created_at);
            """
        )

        # Reporting officer (engineer → dept_head)
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS reports_to INTEGER
                REFERENCES route_card.users(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_reports_to
            ON route_card.users (reports_to);
            """
        )

        print("route_card migrations applied")

        # plant_id on departments (SAP-style WERKS for WC/machine seed)
        cursor.execute(
            """
            ALTER TABLE route_card.departments
            ADD COLUMN IF NOT EXISTS plant_id VARCHAR(32) NOT NULL DEFAULT '';
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS route_card.plants (
                id SERIAL PRIMARY KEY,
                code VARCHAR(32) NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )

        # Seed / upsert BEL department master (safe to re-run; BG excluded)
        # Tuple: code, name, sort_order, plant_id
        bel_departments = [
            ("MR", "MR", 10, "1100"),
            ("MS", "MS", 20, "1200"),
            ("ARMS_AMMO", "Arms & Ammunition", 30, "1300"),
            ("NS1", "NS1", 40, "1400"),
            ("NS2", "NS2", 50, "1500"),
            ("ADSN", "ADSN", 60, "1600"),
            ("MCE_NCS", "MCE/NCS", 70, "1700"),
            ("NWCS", "NWCS", 80, "1800"),
            ("SC", "SC", 90, "1900"),
            ("US", "US", 100, "2000"),
            ("HLS", "HLS", 110, "2100"),
            ("EW_A", "EW&A", 120, "2200"),
            ("SEEKERS", "Seekers (RF & IR)", 130, "2300"),
            ("EM", "EM", 140, "2400"),
            ("COMPONENTS", "Components", 150, "2500"),
            ("SOFTWARE", "Software", 160, "2600"),
            ("AF", "A&F", 170, "2700"),
            ("ES", "ES", 180, "2800"),
            ("CSG", "CSG", 190, "2900"),
            ("CUSTOMER", "Customer", 200, "3000"),
        ]
        # Plants master (one row per WERKS; name mirrors primary department)
        for code, name, sort_order, plant_id in bel_departments:
            cursor.execute(
                """
                INSERT INTO route_card.plants (code, name, description, is_active, sort_order)
                VALUES (%s, %s, %s, TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (plant_id, name, f"Plant for {name}", sort_order),
            )
        print("upserted BEL route_card.plants master")
        bel_codes = [c for c, _, _, _ in bel_departments]
        for code, name, sort_order, plant_id in bel_departments:
            cursor.execute(
                """
                INSERT INTO route_card.departments (code, name, plant_id, is_active, sort_order)
                VALUES (%s, %s, %s, TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    plant_id = EXCLUDED.plant_id,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (code, name, plant_id, sort_order),
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
        print("upserted BEL route_card.departments master (with plant_id)")

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
