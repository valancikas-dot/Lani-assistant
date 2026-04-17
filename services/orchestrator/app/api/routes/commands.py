"""Commands route – main entry point for user commands."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.commands import CommandRequest, CommandResponse
from app.services.command_router import route_command
from app.tools.registry import list_tools

router = APIRouter()


@router.post("/commands", response_model=CommandResponse)
async def submit_command(
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> CommandResponse:
    """
    Accept a natural-language command, classify it, run the matching tool,
    and return a structured result.
    """
    return await route_command(request, db)


@router.get("/tools")
async def available_tools() -> list[dict]:
    """Return the list of all registered tools and their metadata."""
    return list_tools()
