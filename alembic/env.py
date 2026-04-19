"""
alembic/env.py — Alembic migration environment.

Two execution modes:
  offline  → generate a .sql script without connecting to the DB.
             Used for review, audit, or deploying via a DBA.
             Run: alembic upgrade head --sql > migration.sql

  online   → connect to the live DB and apply migrations directly.
             Run: alembic upgrade head

Why we reuse app.models.database.engine for online mode:
  The engine is already configured with the correct SSL mode
  (connect_args={"sslmode": settings.DATABASE_SSLMODE}).
  Reusing it avoids duplicating the connection configuration and ensures
  migrations run over the same SSL-enforced connection as the application.

Why we import all ORM models:
  SQLAlchemy's autogenerate compares Base.metadata (the Python side) against
  the live database schema. If a model is not imported here, autogenerate
  won't know that table exists and may generate a spurious drop_table op.
  The noqa: F401 comments silence the "imported but unused" linter warning.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── Project imports ──────────────────────────────────────────────────────────

from app.core.config import settings
from app.models.database import Base, engine

# Import every ORM model so Base.metadata is fully populated before
# autogenerate or migration execution begins.
from app.models.user import (  # noqa: F401
    User,
    MFASecret,
    Session,
    LoginAttempt,
    Transaction,
    FraudAlert,
    UserBehaviorPattern,
    AuditLog,
    OAuthProvider,
    KnownDevice,
)

# ── Alembic config object ────────────────────────────────────────────────────

config = context.config

# Integrate Python logging with Alembic's log config from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object Alembic inspects for autogenerate.
target_metadata = Base.metadata

# Override sqlalchemy.url with the value from .env so credentials
# never have to appear in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# ── Offline mode ─────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection.
    Generates SQL statements to stdout / a file.
    Useful for review before applying, or for environments where the
    migration runner does not have direct DB access.
    """
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Emit a BEGIN/COMMIT around each migration for safety.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────

def run_migrations_online() -> None:
    """
    Run migrations against a live DB connection.
    Reuses app.models.database.engine so SSL config is inherited automatically.
    """
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Compare server-side column defaults (e.g. func.now()) so
            # autogenerate can detect changes to default values.
            compare_server_default=True,
            # Include schema-level CHECK constraints in comparisons.
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()