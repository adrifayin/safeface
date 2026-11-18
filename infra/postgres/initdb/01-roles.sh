#!/bin/sh
# Creates the database roles. Runs once, on first start of an empty volume.
#   safeface_owner : owns the schema; used only by migrations.
#   safeface_app   : runtime role; privileges are granted per table by the
#                    migration (INSERT/SELECT only on evidence and audit tables).
#   keycloak       : Keycloak's own database.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE safeface_owner LOGIN PASSWORD '${SAFEFACE_OWNER_PASSWORD}';
CREATE ROLE safeface_app LOGIN PASSWORD '${SAFEFACE_APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE safeface OWNER safeface_owner;
REVOKE ALL ON DATABASE safeface FROM PUBLIC;
GRANT CONNECT ON DATABASE safeface TO safeface_app;
CREATE ROLE keycloak LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname safeface <<SQL
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO safeface_app;
SQL
