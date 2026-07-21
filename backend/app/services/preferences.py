from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.db import Database
from app.utils import json_dumps, new_id


class PreferenceService:
    def __init__(self, database: Database):
        self.database = database

    def set_explicit(
        self,
        key: str,
        value: Any,
        kind: str = "soft",
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE preferences SET active = 0 WHERE key = ? AND active = 1",
                (key,),
            )
            preference_id = new_id()
            connection.execute(
                """
                INSERT INTO preferences(
                    id, key, value_json, kind, source, confidence
                ) VALUES (?, ?, ?, ?, 'explicit', ?)
                """,
                (preference_id, key, json_dumps(value), kind, confidence),
            )
            connection.execute(
                "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
            )
        return {
            "id": preference_id,
            "key": key,
            "value": value,
            "kind": kind,
            "source": "explicit",
            "confidence": confidence,
            "search_plan_invalidated": True,
        }

    def set_many(self, updates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = list(updates)
        if not normalized:
            return []
        results: List[Dict[str, Any]] = []
        with self.database.transaction() as connection:
            for update in normalized:
                key = str(update["key"])
                value = update.get("value")
                kind = str(update.get("kind") or "soft")
                confidence = float(update.get("confidence", 1.0))
                connection.execute(
                    "UPDATE preferences SET active = 0 WHERE key = ? AND active = 1",
                    (key,),
                )
                preference_id = new_id()
                connection.execute(
                    """
                    INSERT INTO preferences(
                        id, key, value_json, kind, source, confidence
                    ) VALUES (?, ?, ?, ?, 'explicit', ?)
                    """,
                    (preference_id, key, json_dumps(value), kind, confidence),
                )
                results.append(
                    {
                        "id": preference_id,
                        "key": key,
                        "value": value,
                        "kind": kind,
                        "source": "explicit",
                        "confidence": confidence,
                    }
                )
            connection.execute(
                "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
            )
        return results
