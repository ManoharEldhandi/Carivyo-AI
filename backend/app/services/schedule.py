from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.db import Database
from app.services.profile import ProfileService
from app.services.search import SearchService
from app.utils import json_dumps, json_loads


class SearchScheduleService:
    """Durable, laptop-local scheduling for saved-priority searches.

    It runs while the local Carivyo service is open and catches up once after a
    missed due time. Carivyo intentionally does not install a hidden OS agent.
    """

    SETTINGS_KEY = "search_schedule"
    CADENCES = frozenset({"daily", "weekly"})

    def __init__(
        self,
        database: Database,
        profiles: ProfileService,
        search: SearchService,
    ) -> None:
        self.database = database
        self.profiles = profiles
        self.search = search
        self._task: Optional[asyncio.Task[None]] = None

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()

    @classmethod
    def _default(cls) -> Dict[str, Any]:
        return {
            "enabled": False,
            "cadence": "daily",
            "time": "09:00",
            "weekday": 0,
            "notify": False,
            "next_run_at": None,
            "last_run_id": None,
            "last_completed_at": None,
            "last_status": None,
            "last_error": None,
        }

    @classmethod
    def _validate(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        schedule = {**cls._default(), **(value if isinstance(value, dict) else {})}
        schedule["enabled"] = bool(schedule["enabled"])
        schedule["notify"] = bool(schedule["notify"])
        if schedule["cadence"] not in cls.CADENCES:
            raise ValueError("Search cadence must be daily or weekly")
        try:
            hour, minute = (int(part) for part in str(schedule["time"]).split(":", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Search time must use HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Search time must use HH:MM")
        schedule["time"] = f"{hour:02d}:{minute:02d}"
        try:
            weekday = int(schedule["weekday"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Weekly search day must be between 0 and 6") from exc
        if not 0 <= weekday <= 6:
            raise ValueError("Weekly search day must be between 0 and 6")
        schedule["weekday"] = weekday
        return schedule

    @classmethod
    def _next_run(cls, schedule: Dict[str, Any], now: datetime) -> datetime:
        hour, minute = (int(part) for part in schedule["time"].split(":", 1))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if schedule["cadence"] == "weekly":
            candidate += timedelta(days=(schedule["weekday"] - candidate.weekday()) % 7)
        if candidate <= now:
            candidate += timedelta(days=7 if schedule["cadence"] == "weekly" else 1)
        return candidate

    def _stored(self) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT value_json FROM settings WHERE key = ?", (self.SETTINGS_KEY,)
        )
        return self._validate(json_loads(row["value_json"], {}) if row else {})

    def _save(self, schedule: Dict[str, Any]) -> Dict[str, Any]:
        value = self._validate(schedule)
        self.database.execute(
            """
            INSERT INTO settings(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (self.SETTINGS_KEY, json_dumps(value)),
        )
        return value

    def state(self) -> Dict[str, Any]:
        schedule = self._stored()
        schedule["service_running"] = True
        schedule["requires_open_service"] = True
        schedule["profile_ready"] = self.profiles.active_profile() is not None
        return schedule

    def configure(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        schedule = self._validate({**self._stored(), **payload})
        schedule["next_run_at"] = (
            self._next_run(schedule, self._now()).isoformat()
            if schedule["enabled"]
            else None
        )
        schedule["last_error"] = None
        return self._save(schedule)

    async def tick(self) -> Optional[str]:
        if self._task and not self._task.done():
            return None
        schedule = self._stored()
        if not schedule["enabled"] or not self.profiles.active_profile():
            return None
        now = self._now()
        try:
            due = datetime.fromisoformat(str(schedule.get("next_run_at") or ""))
        except ValueError:
            due = now
        if due > now:
            return None

        schedule["next_run_at"] = self._next_run(schedule, now).isoformat()
        schedule["last_error"] = None
        self._save(schedule)
        try:
            run = self.search.create_run(reason="scheduled")
        except Exception as exc:
            schedule["last_error"] = str(exc)[:500]
            self._save(schedule)
            return None
        schedule["last_run_id"] = run["id"]
        self._save(schedule)
        self._task = asyncio.create_task(self._run_and_record(run["id"]))
        return run["id"]

    async def _run_and_record(self, run_id: str) -> None:
        try:
            await self.search.run(run_id)
            run = self.search.run_status(run_id)
            schedule = self._stored()
            schedule["last_run_id"] = run_id
            schedule["last_completed_at"] = self._now().isoformat()
            schedule["last_status"] = run["status"]
            schedule["last_error"] = run.get("error")
            self._save(schedule)
        except Exception as exc:  # SearchService normally records failures itself.
            schedule = self._stored()
            schedule["last_run_id"] = run_id
            schedule["last_completed_at"] = self._now().isoformat()
            schedule["last_status"] = "failed"
            schedule["last_error"] = str(exc)[:500]
            self._save(schedule)
