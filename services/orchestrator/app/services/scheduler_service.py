"""
Scheduler Service – proactive task scheduling for Lani.

Supports:
  • One-time reminders  ("primink man rytoj 9:00", "remind me tomorrow at 9am")
  • Recurring cron jobs ("tikrink el. paštą kiekvieną rytą", "check email every morning")
  • Arbitrary plan execution on schedule

Persistence:
  All scheduled tasks are stored in the `memory_entries` table under
  category = "scheduled_tasks".  On startup the scheduler rehydrates
  every active task from the DB so nothing is lost after a restart.

APScheduler is used under the hood (AsyncIOScheduler + AsyncIOExecutor).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Conditional APScheduler import – graceful if not installed
# ---------------------------------------------------------------------------
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]
    DateTrigger = None  # type: ignore[assignment]
    _APSCHEDULER_AVAILABLE = False
    log.warning("apscheduler not installed – scheduler_service will be a no-op. "
                "Run: pip install apscheduler")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
_scheduler: Optional[Any] = None   # AsyncIOScheduler instance or None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def start_scheduler() -> None:
    """Start the APScheduler and restore persisted tasks from DB."""
    if not _APSCHEDULER_AVAILABLE:
        return

    if AsyncIOScheduler is None:
        return

    scheduler = AsyncIOScheduler()
    scheduler.start()
    global _scheduler
    _scheduler = scheduler
    log.info("Scheduler started.")

    # Register built-in maintenance jobs
    _register_maintenance_jobs()

    # Restore user-defined jobs from DB
    await _restore_jobs()


def _register_maintenance_jobs() -> None:
    """Register recurring system maintenance jobs (run once on startup)."""
    if not _scheduler or CronTrigger is None:
        return

    # Weekly: clean up old .bak files (keep 3 newest)
    _scheduler.add_job(
        _cleanup_db_backups,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="__maintenance_backup_cleanup__",
        replace_existing=True,
    )
    # Daily: prune old conversation history (keep 30 days)
    _scheduler.add_job(
        _prune_old_conversation_history,
        trigger=CronTrigger(hour=2, minute=30),
        id="__maintenance_history_prune__",
        replace_existing=True,
    )
    # Daily: prune low-importance episodic events (keep 90 days)
    _scheduler.add_job(
        _prune_old_episodic_events,
        trigger=CronTrigger(hour=3, minute=30),
        id="__maintenance_episodic_prune__",
        replace_existing=True,
    )
    log.info("Maintenance jobs registered.")


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped.")
    _scheduler = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def schedule_task(
    command: str,
    run_at: Optional[datetime] = None,
    cron_expr: Optional[str] = None,
    task_id: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """
    Schedule *command* to run at a specific time or on a cron schedule.

    Exactly one of `run_at` or `cron_expr` must be supplied.
    Returns a dict with task metadata (id, command, trigger, status).
    """
    if run_at is None and cron_expr is None:
        raise ValueError("Either run_at or cron_expr must be provided")

    task_id = task_id or str(uuid.uuid4())

    trigger_info: Dict[str, Any]
    if run_at is not None:
        trigger_info = {"type": "date", "run_at": run_at.isoformat()}
    else:
        trigger_info = {"type": "cron", "cron_expr": cron_expr}

    task_record = {
        "id": task_id,
        "command": command,
        "trigger": trigger_info,
        "created_at": _utcnow().isoformat(),
        "status": "active",
    }

    # Persist to DB
    if db is not None:
        await _persist_task(db, task_id, task_record)

    # Register with APScheduler
    if _APSCHEDULER_AVAILABLE and _scheduler:
        _register_apscheduler_job(task_id, command, run_at, cron_expr)

    log.info("Scheduled task %s: %r trigger=%s", task_id, command, trigger_info)
    return task_record


async def list_tasks(db) -> List[Dict[str, Any]]:
    """Return all active scheduled tasks from DB."""
    return await _load_tasks(db)


async def delete_task(task_id: str, db) -> bool:
    """
    Cancel and delete a scheduled task.
    Returns True if found and removed, False otherwise.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.memory_entry import MemoryEntry
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as session:
        stmt = (
            update(MemoryEntry)
            .where(
                MemoryEntry.category == "scheduled_tasks",
                MemoryEntry.key == f"task_{task_id}",
            )
            .values(status="deleted")
        )
        result = await session.execute(stmt)
        await session.commit()
    removed = bool(getattr(result, "rowcount", 0) and getattr(result, "rowcount", 0) > 0)

    # Also remove from live scheduler
    if _APSCHEDULER_AVAILABLE and _scheduler:
        try:
            _scheduler.remove_job(task_id)
        except Exception:
            pass

    return removed


async def parse_schedule_from_command(command: str) -> Dict[str, Any]:
    """
    Extract scheduling intent from natural-language command.

    Returns a dict:
      {
        "clean_command": str,   # command without the time phrase
        "run_at": datetime|None,
        "cron_expr": str|None,
        "detected": bool,
      }
    """
    cmd = command.strip()
    now = datetime.now()
    result: Dict[str, Any] = {
        "clean_command": cmd,
        "run_at": None,
        "cron_expr": None,
        "detected": False,
    }

    # ── One-time patterns ──────────────────────────────────────────────
    # "rytoj 9:00" / "tomorrow at 9am"
    m = re.search(
        r"\b(rytoj|tomorrow)\b.*?(\d{1,2})[:\.](\d{2})?\s*(am|pm|val\.?)?",
        cmd, re.I
    )
    if m:
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        if m.group(4) and m.group(4).lower() == "pm" and hour < 12:
            hour += 12
        run_at = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        result.update(run_at=run_at, detected=True,
                      clean_command=cmd[:m.start()].strip() + " " + cmd[m.end():].strip())
        return result

    # "po X minučių / valandų" / "in X minutes/hours"
    m = re.search(
        r"\b(po|in)\b\s*(\d+)\s*(min(?:učių|utes?)?|val(?:andų|ours?|h)?|sec(?:undžių|onds?)?)",
        cmd, re.I
    )
    if m:
        amount = int(m.group(2))
        unit = m.group(3).lower()
        if unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("val") or unit.startswith("h"):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(seconds=amount)
        result.update(run_at=now + delta, detected=True,
                      clean_command=cmd[:m.start()].strip() + " " + cmd[m.end():].strip())
        return result

    # ── Recurring (cron) patterns ──────────────────────────────────────
    # "kiekvieną rytą" / "every morning"
    morning_map = {"kiekvieną rytą": "0 8 * * *", "every morning": "0 8 * * *",
                   "every day at 8": "0 8 * * *"}
    noon_map   = {"kiekvieną dieną pietų": "0 12 * * *", "every day at noon": "0 12 * * *"}
    evening_map = {"kiekvieną vakarą": "0 20 * * *", "every evening": "0 20 * * *"}
    hourly_map  = {"kas valandą": "0 * * * *", "every hour": "0 * * * *",
                   "hourly": "0 * * * *"}

    for mapping in (morning_map, noon_map, evening_map, hourly_map):
        for phrase, cron in mapping.items():
            if phrase in cmd.lower():
                result.update(cron_expr=cron, detected=True,
                              clean_command=cmd.lower().replace(phrase, "").strip())
                return result

    # "kiekvieną dieną HH:MM" / "every day at HH:MM"
    m = re.search(
        r"\b(kiekvien[aą]\s*dien[aą]|every\s*day)\b.*?(\d{1,2})[:\.](\d{2})",
        cmd, re.I
    )
    if m:
        hour = int(m.group(2))
        minute = int(m.group(3))
        cron = f"{minute} {hour} * * *"
        result.update(cron_expr=cron, detected=True,
                      clean_command=cmd[:m.start()].strip() + " " + cmd[m.end():].strip())
        return result

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _register_apscheduler_job(
    task_id: str,
    command: str,
    run_at: Optional[datetime],
    cron_expr: Optional[str],
) -> None:
    """Add a job to the live APScheduler instance."""
    if _scheduler is None:
        return

    if run_at is not None:
        if DateTrigger is None:
            return
        trigger = DateTrigger(run_date=run_at)
    else:
        if not cron_expr or CronTrigger is None:
            return
        parts = cron_expr.split()
        if len(parts) == 5:
            minute, hour, day, month, dow = parts
            trigger = CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=dow
            )
        else:
            log.warning("Invalid cron expression %r – skipping job %s", cron_expr, task_id)
            return

    _scheduler.add_job(
        _execute_scheduled_command,
        trigger=trigger,
        id=task_id,
        replace_existing=True,
        args=[command, task_id],
    )


async def _execute_scheduled_command(command: str, task_id: str) -> None:
    """Callback invoked by APScheduler when a job fires."""
    log.info("Scheduler firing task %s: %r", task_id, command)
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.workflow_planner import plan_workflow
        from app.services.plan_executor import execute_plan

        async with AsyncSessionLocal() as db:
            plan = plan_workflow(command)
            await execute_plan(plan, db)
            log.info("Scheduled task %s completed.", task_id)
    except Exception as exc:
        log.exception("Scheduled task %s failed: %s", task_id, exc)


async def _persist_task(db, task_id: str, record: Dict[str, Any]) -> None:
    """Write task record to memory_entries (category=scheduled_tasks)."""
    try:
        from app.services.memory_service import write_memory
        from app.schemas.memory import MemoryEntryCreate
        payload = MemoryEntryCreate(
            category="scheduled_tasks",
            key=f"task_{task_id}",
            value=record,
            source="scheduler",
            confidence=1.0,
            pinned=False,
        )
        await write_memory(db=db, payload=payload)
    except Exception as exc:
        log.warning("Could not persist scheduled task %s: %s", task_id, exc)


async def _load_tasks(db) -> list:
    """Load all active scheduled tasks from DB."""
    try:
        from app.services.memory_service import get_all
        entries = await get_all(db, category="scheduled_tasks", status="active")
        return [e.value for e in entries if isinstance(e.value, dict)]
    except Exception:
        return []


async def _restore_jobs() -> None:
    """On startup, reload persisted jobs into the live scheduler."""
    if not _APSCHEDULER_AVAILABLE or not _scheduler:
        return
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            tasks = await list_tasks(db)
        now = _utcnow()
        restored = 0
        for t in tasks:
            trigger_info = t.get("trigger", {})
            task_id = t.get("id", str(uuid.uuid4()))
            command = t.get("command", "")
            if trigger_info.get("type") == "date":
                run_at = datetime.fromisoformat(trigger_info["run_at"])
                if run_at < now:
                    log.debug("Skipping past one-time task %s", task_id)
                    continue
                _register_apscheduler_job(task_id, command, run_at=run_at, cron_expr=None)
                restored += 1
            elif trigger_info.get("type") == "cron":
                _register_apscheduler_job(task_id, command, run_at=None,
                                          cron_expr=trigger_info.get("cron_expr", ""))
                restored += 1
        log.info("Restored %d scheduled jobs from DB.", restored)
    except Exception as exc:
        log.warning("Could not restore scheduled jobs: %s", exc)


# ---------------------------------------------------------------------------
# Maintenance callbacks
# ---------------------------------------------------------------------------

async def _cleanup_db_backups() -> None:
    """
    Weekly job: keep only the 3 newest *.bak files next to assistant.db.
    Deletes older ones to free disk space.
    """
    import glob
    import os
    try:
        from app.core.config import settings as cfg
        db_path = cfg.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        pattern = os.path.join(db_dir, "*.bak*")
        bak_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        to_delete = bak_files[3:]  # keep newest 3
        for f in to_delete:
            try:
                os.remove(f)
                log.info("[maintenance] Deleted old backup: %s", f)
            except Exception as e:
                log.warning("[maintenance] Could not delete %s: %s", f, e)
        if to_delete:
            log.info("[maintenance] Cleaned up %d old backup(s).", len(to_delete))
    except Exception as exc:
        log.warning("[maintenance] backup cleanup failed: %s", exc)


async def _prune_old_conversation_history() -> None:
    """
    Daily job: delete conversation messages older than 30 days to keep DB lean.
    """
    import datetime as dt
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.conversation import ConversationMessage
        from sqlalchemy import delete

        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                delete(ConversationMessage)
                .where(ConversationMessage.created_at < cutoff)
            )
            await db.commit()
            deleted = int(getattr(result, "rowcount", 0) or 0)
        if deleted:
            log.info("[maintenance] Pruned %d old conversation messages (>30 days).", deleted)
    except Exception as exc:
        log.warning("[maintenance] history prune failed: %s", exc)


async def _prune_old_episodic_events() -> None:
    """
    Daily job: delete low-importance episodic events older than 90 days.
    High-importance events (score >= 0.7) are kept indefinitely.
    """
    try:
        from app.services.episodic_memory_service import prune_old_events
        deleted = await prune_old_events(days=90)
        if deleted:
            log.info("[maintenance] Pruned %d old episodic events (>90 days, low importance).", deleted)
    except Exception as exc:
        log.warning("[maintenance] episodic prune failed: %s", exc)
