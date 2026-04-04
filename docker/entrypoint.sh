#!/usr/bin/env sh
set -eu

# Database initialisation & migrations are now handled inside the
# application itself (papervisor.db.init_db.init_db):
#
#   • Fresh database  → create_all from models + stamp Alembic to heads
#   • Existing database → alembic upgrade head
#
# This entrypoint simply launches the app.  Set
# PAPERVISOR_SKIP_MIGRATIONS=1 to bypass the in-app auto-migration.

exec "$@"
