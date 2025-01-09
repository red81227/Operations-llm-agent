"""This file creates the fastapi service."""
# coding=utf-8
# pylint: disable=unused-variable,too-many-locals,too-many-statements,ungrouped-imports
# import relation package.
import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from src.router.agent import create_agent_router
from src.router.health_check import create_health_check_router
# import project package.
from config.logger_setting import log
from src.service.agent import AgentService
from src.util import function_utils

def create_app():
    """The function to creates the fastapi service."""

    version=function_utils.health_check_parsing()

    # Initial fastapi app
    app = FastAPI(title="Service Ems school LLM Swagger API",
                description="This is swagger api spec document for the service-operation-agent project.",
                version=version)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        # pylint: disable=W0613,W0612
        return JSONResponse(status_code=400, content=jsonable_encoder({'errCode': '601', 'errMsg': 'Invalid Input', 'errDetail': exc.errors()}),)


    agent_service = AgentService()
    
    # Health check router for this service
    health_check_router = create_health_check_router()
    agent_router = create_agent_router(agent_service)


    api_version = f"/v1/"

    app.include_router(health_check_router, prefix=f"{api_version}service",
                       tags=["Health Check"])
    app.include_router(agent_router, prefix=f"{api_version}agent",
                          tags=["Agent Service"])
  

    log.info("start fastapi service.")
    return app