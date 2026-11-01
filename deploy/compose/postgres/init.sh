#!/bin/sh
# Creates the least-privilege roles used by the application (see design D4):
#   pa_owner        owns the schema and runs migrations (POSTGRES_USER)
#   pa_app          application role; subject to RLS, no DELETE on append-only tables
#   pa_maintenance  retention purge jobs only
# Also creates separate databases for integration tests and browser end-to-end tests.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE pa_app LOGIN PASSWORD '${PA_APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pa_maintenance LOGIN PASSWORD '${PA_MAINTENANCE_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE DATABASE pricing_test OWNER ${POSTGRES_USER};
CREATE DATABASE pricing_e2e OWNER ${POSTGRES_USER};
GRANT CONNECT ON DATABASE pricing TO pa_app, pa_maintenance;
GRANT CONNECT ON DATABASE pricing_test TO pa_app, pa_maintenance;
GRANT CONNECT ON DATABASE pricing_e2e TO pa_app, pa_maintenance;
SQL
