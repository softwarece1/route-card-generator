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
            CREATE TABLE IF NOT EXISTS route_card.auth_sessions (
                id SERIAL PRIMARY KEY,
                "user" INTEGER NOT NULL
                    REFERENCES route_card.users(id) ON DELETE CASCADE,
                access_jti VARCHAR(64) NOT NULL UNIQUE,
                user_agent VARCHAR(512) NOT NULL DEFAULT '',
                ip VARCHAR(64) NOT NULL DEFAULT '',
                expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                revoked_at TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_active
            ON route_card.auth_sessions ("user", revoked_at);
            """
        )

        # Self-service signup approval (engineer → dept_head / admin)
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_status VARCHAR(32) NOT NULL DEFAULT 'approved';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_remark TEXT NOT NULL DEFAULT '';
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_decided_at TIMESTAMP WITHOUT TIME ZONE;
            """
        )
        cursor.execute(
            """
            ALTER TABLE route_card.users
            ADD COLUMN IF NOT EXISTS approval_decided_by INTEGER
                REFERENCES route_card.users(id) ON DELETE SET NULL;
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_users_approval_status_dept
            ON route_card.users (approval_status, dept);
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
        # Legacy uniqueness was (dept, code); plant-scoped masters need (plant, code)
        cursor.execute("DROP INDEX IF EXISTS route_card.ux_work_centers_dept_code;")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_plant_code
            ON route_card.work_centers (plant, code)
            WHERE is_active = TRUE AND COALESCE(plant, '') <> '';
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_work_centers_dept_code
            ON route_card.work_centers (dept, code)
            WHERE is_shared = FALSE AND is_active = TRUE
              AND COALESCE(plant, '') = '';
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

        cursor.execute(
            """
            ALTER TABLE route_card.plants
            ADD COLUMN IF NOT EXISTS work_center_synced_at
                TIMESTAMP WITHOUT TIME ZONE NULL;
            """
        )

        # Real SAP plant / WERKS codes from end-user work-centres list
        sap_plant_codes = [
            "1110", "1111", "1114", "1115", "1120", "1130", "1131", "1132",
            "1140", "1141", "1142", "1143", "1150", "1151", "1152", "1153",
            "1154", "1155", "1156", "1157", "1160", "1161", "1170", "1171",
            "1172", "1173", "1174", "1175", "1176", "1178", "1180", "1181",
            "1182", "1183", "1184", "1186", "1190", "1191", "1210", "1310",
            "1320", "1330", "1340", "1350", "1360", "1410", "1411", "1510",
            "1610", "1710",
        ]
        dummy_plant_codes = [
            "1100", "1200", "1300", "1400", "1500", "1600", "1700", "1800",
            "1900", "2000", "2100", "2200", "2300", "2400", "2500", "2600",
            "2700", "2800", "2900", "3000",
        ]

        for idx, plant_code in enumerate(sap_plant_codes, start=1):
            cursor.execute(
                """
                INSERT INTO route_card.plants (code, name, description, is_active, sort_order)
                VALUES (%s, %s, %s, TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (plant_code, plant_code, "", idx * 10),
            )

        # Remove legacy dummy SBU plant codes (1100–3000)
        cursor.execute(
            """
            DELETE FROM route_card.plants
            WHERE code = ANY(%s);
            """,
            (dummy_plant_codes,),
        )
        print("upserted SAP route_card.plants master; removed dummy plant codes")

        # Seed / upsert BEL SBU master (safe to re-run; BG excluded)
        # plant_id left blank until SBU → plant mapping is provided
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
                INSERT INTO route_card.departments (code, name, plant_id, is_active, sort_order)
                VALUES (%s, %s, '', TRUE, %s)
                ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    is_active = TRUE,
                    sort_order = EXCLUDED.sort_order;
                """,
                (code, name, sort_order),
            )
        # Clear dummy plant codes from SBUs (do not invent replacements)
        cursor.execute(
            """
            UPDATE route_card.departments
            SET plant_id = ''
            WHERE plant_id = ANY(%s);
            """,
            (dummy_plant_codes,),
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
        print("upserted BEL route_card.departments (SBU) master; cleared dummy plant_id")

        # Admin plant override for queued analyze jobs (WC linking)
        cursor.execute(
            """
            ALTER TABLE route_card.analyze_jobs
            ADD COLUMN IF NOT EXISTS plant VARCHAR(32) NULL;
            """
        )

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
