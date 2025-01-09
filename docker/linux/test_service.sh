cd ../..
DOCKER_NETWORK_NAME=test-enterprise-ems

docker network create $DOCKER_NETWORK_NAME
# setup PostgreSQL for test
docker run -d --network $DOCKER_NETWORK_NAME -p 5432 \
    -e POSTGRES_HOST_AUTH_METHOD='trust' \
    -e POSTGRES_USER='root' \
    -e POSTGRES_PASSWORD='root' \
    -e POSTGRES_DB=test-enterpriseEMS \
    --name test-postgres \
    -v ${PWD}/data/sql/postgresql:/tmp/sql \
    postgres:13.5-alpine

docker run -itd --network $DOCKER_NETWORK_NAME --expose=6379 --name test-redis redis:6.0-alpine

docker run -itd --network $DOCKER_NETWORK_NAME --expose=6379 --name test-redis redis:6.0-alpine

./docker/linux/docker-install-postgres-test.sh

export PROJECT_DIR=/home/app/workdir
docker run --rm --env-file ./docker/unittest.env --network $DOCKER_NETWORK_NAME -v "$(pwd)":$PROJECT_DIR -w $PROJECT_DIR -e PYTHONPATH=$PROJECT_DIR ubuntu:20.04 /bin/bash  -c "apt-get update && apt-get install software-properties-common --yes && apt-get install build-essential wget -y && apt-get install python3-pip -y && pip install --upgrade pip && pip3 install -r docker/requirements.txt && pip3 install -r docker/requirements-test.txt && celery -A src.service.event.celery_app worker --loglevel=INFO --concurrency=4 && pytest -q -p no:warnings --cov-config=config/.pytest_coveragerc --cov=. --cov-report term-missing -o log_cli=true --capture=no tests/"

docker rm -f test-postgres
docker rm -f test-redis
docker network rm $DOCKER_NETWORK_NAME

cd docker/windows