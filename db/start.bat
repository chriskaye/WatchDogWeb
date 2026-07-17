@echo off
echo Starting containers...
docker compose up -d

echo Waiting for Postgres to be ready...
timeout /t 5 >nul

echo Restoring database...
docker exec watchdogweb-db-1 pg_restore -U postgres -d postgres /backups/db.dump

echo Done.
pause
