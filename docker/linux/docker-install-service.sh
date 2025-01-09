cd ../..

mkdir $(pwd)/models
chmod a+w $(pwd)/models
mkdir $(pwd)/meta_data
chmod a+w $(pwd)/meta_data

mkdir -p /home/hankliang/data/database /home/hankliang/data/ems-enterprise-ai /home/hankliang/data/ems-enterprise-ai/logs

chmod a+w /home/hankliang/data/ems-enterprise-ai/logs /home/hankliang/data/database/
cd docker
docker-compose -f docker-compose.postgre.install.yml up -d
docker exec -it postgre-install bash -c "
until pg_isready -h postgre-install -p 5432 -U postgres
do
  echo \"Waiting for PostgreSQL...\"
  sleep 1
done
psql -U root -d postgres -c 'CREATE DATABASE \"enterpriseEMS\";'
psql -U root -d enterpriseEMS -f /tmp/sql/ems_ai.sql
psql -U root -d enterpriseEMS -f /tmp/sql/system-data.sql
"

echo "Install prostgres finished."

docker rm -f postgre-install

echo "Remove postgre-install container."

cd linux