# Postgres 16 with PostGIS (geo queries) and pgvector (semantic search).
#
# No official image ships both. Instead of apt-installing pgvector (needs network
# access to Debian mirrors during the build), we copy the compiled extension out of
# the official pgvector image. vector.so only links against libc (needs glibc >= 2.14),
# so it runs on the PostGIS image's older Debian. Postgres extensions are compatible
# across 16.x minor versions. In production, Supabase/Neon provide both extensions.
FROM pgvector/pgvector:0.8.0-pg16 AS pgvector

FROM postgis/postgis:16-3.5

COPY --from=pgvector /usr/lib/postgresql/16/lib/vector.so /usr/lib/postgresql/16/lib/
COPY --from=pgvector /usr/share/postgresql/16/extension/vector* /usr/share/postgresql/16/extension/

# Creates the test database next to the main one on first start.
COPY init-test-db.sql /docker-entrypoint-initdb.d/20-init-test-db.sql
