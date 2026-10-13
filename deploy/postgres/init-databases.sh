#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=app_password="$ACTVERO_DB_PASSWORD" \
  --set=identity_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE ROLE actvero LOGIN PASSWORD :'app_password';
CREATE DATABASE actvero OWNER actvero;
CREATE ROLE actvero_identity LOGIN PASSWORD :'identity_password';
CREATE DATABASE actvero_identity OWNER actvero_identity;
REVOKE CONNECT ON DATABASE actvero FROM PUBLIC;
REVOKE CONNECT ON DATABASE actvero_identity FROM PUBLIC;
GRANT CONNECT ON DATABASE actvero TO actvero;
GRANT CONNECT ON DATABASE actvero_identity TO actvero_identity;
SQL
