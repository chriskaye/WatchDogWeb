@echo off
echo Backing up database...
docker exec watchdogweb-db-1 pg_dump -U postgres -d postgres -F c -b -f /backups/db.dump
echo Stopping containers...
docker compose down

echo Done.
pause
