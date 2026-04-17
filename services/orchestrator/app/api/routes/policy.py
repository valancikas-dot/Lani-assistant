"""
API routes for the Policy Engine.

POST /api/v1/policy/evaluate         – evaluate a single action
POST /api/v1/policy/evaluate-plan    – evaluate a list of plan steps
GET  /api/v1/policy/rules            – describe current policy rules
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.settings import UserSettings
from app.services.policy_engine import (
    evaluate,
    evaluate_plan,
    build_context_from_settings,
    PolicyContext,
)
from app.services.session_manager import list_active_account_types

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _load_policy_context(db: AsyncSession) -> PolicyContext:
    row = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    settings = row.scalar_one_or_none()
    active_accounts = list_active_account_types()
    return build_context_from_settings(settings, active_accounts)


@router.post("/policy/evaluate", tags=["policy"])
async def evaluate_action(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Evaluate a single action against the current policy.

    Body: { "action": "tool_name", "params": {}, "command_text": "" }
    """
    action = body.get("action", "")
    params = body.get("params", {})
    ctx = await _load_policy_context(db)
    ctx.command_text = body.get("command_text", "")

    decision = evaluate(action, params, ctx)
    return {
        "action": action,
        "verdict": decision.verdict,
        "reason": decision.reason,
        "risk_level": decision.risk_level,
    }


@router.post("/policy/evaluate-plan", tags=["policy"])
async def evaluate_plan_steps(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Evaluate a list of plan steps.

    Body: { "steps": [{"tool": "...", "args": {}}, ...] }
    """
    steps: List[Dict[str, Any]] = body.get("steps", [])
    ctx = await _load_policy_context(db)

    decisions = evaluate_plan(steps, ctx)
    return {
        "results": [
            {
                "tool": steps[i].get("tool", ""),
                "verdict": d.verdict,
                "reason": d.reason,
                "risk_level": d.risk_level,
            }
            for i, d in enumerate(decisions)
        ]
    }


@router.get("/policy/rules", tags=["policy"])
async def get_policy_rules() -> Dict[str, Any]:
    """Describe the active policy rules in human-readable form."""
    return {
        "rules": [
            {
                "priority": 1,
                "condition": "risk_level == critical",
                "verdict": "require_approval",
                "description": "All CRITICAL risk actions always require human confirmation.",
            },
            {
                "priority": 2,
                "condition": "risk_level == high",
                "verdict": "require_approval",
                "description": "HIGH risk actions require approval.",
            },
            {
                "priority": 3,
                "condition": "security_mode == strict AND sensitive domain detected",
                "verdict": "require_approval",
                "description": "Sensitive domains (banking, auth, etc.) require approval in strict mode.",
            },
            {
                "priority": 4,
                "condition": "allowed_accounts not satisfied",
                "verdict": "deny",
                "description": "Action requires an account that is not connected.",
            },
            {
                "priority": 5,
                "condition": "capability.requires_approval == true",
                "verdict": "require_approval",
                "description": "Tool is explicitly configured to always require approval.",
            },
            {
                "priority": 6,
                "condition": "security_mode == strict AND risk_level == medium",
                "verdict": "require_approval",
                "description": "Medium-risk actions require approval in strict mode.",
            },
            {
                "priority": 7,
                "condition": "default",
                "verdict": "allow",
                "description": "Action is within policy – proceed.",
            },
        ]
    }
