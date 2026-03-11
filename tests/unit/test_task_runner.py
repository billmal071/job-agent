"""Unit tests for the TaskRunner class."""

from __future__ import annotations

import time

from job_agent.dashboard.tasks import TaskRunner


def test_run_and_complete():
    runner = TaskRunner()

    def simple_fn(x, y):
        return x + y

    task_id = runner.run("add", simple_fn, 1, 2)
    time.sleep(0.1)

    status = runner.get_status(task_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["result"] == 3
    assert status["error"] is None
    assert status["finished_at"] is not None


def test_run_and_fail():
    runner = TaskRunner()

    def failing_fn():
        raise ValueError("something went wrong")

    task_id = runner.run("fail", failing_fn)
    time.sleep(0.1)

    status = runner.get_status(task_id)
    assert status is not None
    assert status["status"] == "failed"
    assert status["error"] == "something went wrong"
    assert status["result"] is None
    assert status["finished_at"] is not None


def test_get_status_not_found():
    runner = TaskRunner()
    result = runner.get_status("nonexistent-task-id")
    assert result is None


def test_list_tasks():
    runner = TaskRunner()

    def noop():
        return None

    task_id_1 = runner.run("task-one", noop)
    task_id_2 = runner.run("task-two", noop)
    task_id_3 = runner.run("task-three", noop)
    time.sleep(0.1)

    tasks = runner.list_tasks()
    task_ids = {t["task_id"] for t in tasks}
    assert task_id_1 in task_ids
    assert task_id_2 in task_ids
    assert task_id_3 in task_ids
    assert len(tasks) >= 3
