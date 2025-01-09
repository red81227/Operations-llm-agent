"""This file define the api of service health check"""

from fastapi import APIRouter, HTTPException, status
from config.logger_setting import log

# import psycopg2


from src.util import function_utils
from src.models.health_check import HealthCheckBaseModel
# pylint: disable=W0612


def create_health_check_router():
    """This function is for creating health check router"""
    router = APIRouter()

    @router.get("/health_check", response_model=HealthCheckBaseModel, status_code=200)
    def health_check() -> HealthCheckBaseModel:
        """This method is for health check"""
        try:
            version_str = function_utils.health_check_parsing()
            response = HealthCheckBaseModel(
                version=version_str, msg="Service Up", error="")
            return response
        # except psycopg2.OperationalError as e:
        #     raise HTTPException(
        #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        #         detail="Failed to connect to database")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            log.error(e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="interal server error")
    return router
