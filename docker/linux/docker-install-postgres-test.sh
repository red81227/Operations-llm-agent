docker exec -i test-postgres bash -c "
until pg_isready -h test-postgres -p 5432 -U postgres
do
  echo \"Waiting for PostgreSQL...\"
  sleep 1
done
psql -U root -d postgres -c 'CREATE DATABASE \"test-agent\";'
psql -U root -d test-agent -f /tmp/sql/agent.sql
psql -U root -d test-agent -f /tmp/sql/system-data.sql
psql -U root -d test-agent -f /tmp/sql/testing-data.sql
"