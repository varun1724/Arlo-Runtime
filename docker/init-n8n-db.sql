-- Create a separate database for n8n
-- This runs automatically on first Postgres boot via docker-entrypoint-initdb.d
SELECT 'CREATE DATABASE n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
