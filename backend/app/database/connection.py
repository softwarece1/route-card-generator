"""Pony ORM bind — route_card schema only."""

from pony.orm import Database, db_session

from app.config.settings import settings

db = Database()


def connect_to_db():
    db.bind(
        provider="postgres",
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    )

    with db_session:
        conn = db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS route_card")
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Failed to create route_card schema: {e}") from e
        finally:
            cursor.close()

    from .migrations_route_card import run_migrations

    run_migrations()

    # Register entities before mapping
    from app.route_card import models as route_card_models  # noqa: F401

    db.generate_mapping(create_tables=True)
