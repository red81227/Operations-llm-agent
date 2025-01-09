"""This file define the api of service health check"""

from fastapi import APIRouter, HTTPException, status
from config.logger_setting import log


from src.models.query import Output, Query
from src.service.agent import AgentService
# pylint: disable=W0612


def create_agent_router(agent_service: AgentService):
    """This function is for creating agent router"""
    router = APIRouter()

    @router.post("/chat", response_model=Output, status_code=200)
    def chat(query: Query) -> Output:
        """This method is for health check"""
        try:
            return agent_service.chat(query=query.input, user_id=query.user_id)

        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            log.error(e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="interal server error")
    return router
