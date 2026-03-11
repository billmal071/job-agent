"""In-memory background task runner using threading."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class TaskStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskInfo:
    task_id: str
    name: str
    status: TaskStatus
    started_at: datetime
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None


class TaskRunner:
    """Simple in-memory task tracker that runs functions in background threads."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    def run(self, name: str, fn: Callable, *args: Any, **kwargs: Any) -> str:
        """Start a function in a background thread. Returns a task_id."""
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(
            task_id=task_id,
            name=name,
            status=TaskStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._tasks[task_id] = info

        thread = threading.Thread(
            target=self._execute, args=(task_id, fn, args, kwargs), daemon=True
        )
        thread.start()
        return task_id

    def _execute(self, task_id: str, fn: Callable, args: tuple, kwargs: dict) -> None:
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                task = self._tasks[task_id]
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.finished_at = datetime.now(timezone.utc)
        except Exception as exc:
            with self._lock:
                task = self._tasks[task_id]
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                task.finished_at = datetime.now(timezone.utc)

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        """Return status dict for a task, or None if not found."""
        with self._lock:
            info = self._tasks.get(task_id)
        if info is None:
            return None
        return {
            "task_id": info.task_id,
            "name": info.name,
            "status": info.status.value,
            "started_at": info.started_at.isoformat(),
            "finished_at": info.finished_at.isoformat() if info.finished_at else None,
            "result": info.result,
            "error": info.error,
        }

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return all tasks, most recent first."""
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.started_at, reverse=True)
        return [
            {
                "task_id": t.task_id,
                "name": t.name,
                "status": t.status.value,
                "started_at": t.started_at.isoformat(),
            }
            for t in tasks
        ]


# Module-level singleton
task_runner = TaskRunner()
