#!/usr/bin/env python3
"""tasks/queue.jsonl (JSONL: 한 줄에 JSON 객체 하나) 조작 헬퍼.

이름을 queue.py가 아니라 task_queue.py로 지은 이유: Python 표준 라이브러리에
이미 'queue' 모듈이 있어서, 같은 이름으로 만들면 sys.path 우선순위에 따라
표준 라이브러리를 가려버릴 수 있기 때문입니다.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import common

QUEUE_FILE: Path = common.QUEUE_FILE


def _read_all() -> list[dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    tasks = []
    with QUEUE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tasks.append(json.loads(line))
    return tasks


def _write_all(tasks: list[dict[str, Any]]) -> None:
    tmp = QUEUE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    tmp.replace(QUEUE_FILE)


def all_tasks() -> list[dict[str, Any]]:
    """큐에 있는 모든 작업을 그대로 반환한다(진행 상황 요약, 종료 조건 판단용)."""
    return _read_all()


def get(task_id: str) -> Optional[dict[str, Any]]:
    for t in _read_all():
        if t.get("id") == task_id:
            return t
    return None


def next_with_status(status: str) -> Optional[dict[str, Any]]:
    for t in _read_all():
        if t.get("status") == status:
            return t
    return None


def next_with_status_and_complexity(status: str, complexity: str) -> Optional[dict[str, Any]]:
    for t in _read_all():
        if t.get("status") == status and t.get("complexity") == complexity:
            return t
    return None


def new_id(prefix: str = "task") -> str:
    """타임스탬프 + 짧은 난수 접미사로 유일한 작업 id를 만든다.

    plan_project.py처럼 한 번에 여러 작업을 연달아 추가할 때, 초 단위
    타임스탬프만 쓰면 같은 초에 추가된 작업들의 id가 충돌할 수 있어서
    난수 접미사를 붙인다.
    """
    return f"{prefix}-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def add(task: dict[str, Any]) -> None:
    tasks = _read_all()
    tasks.append(task)
    _write_all(tasks)


def update(task_id: str, **fields: Any) -> None:
    tasks = _read_all()
    for t in tasks:
        if t.get("id") == task_id:
            t.update(fields)
    _write_all(tasks)


def bump_retry(task_id: str, status: str = "todo") -> None:
    tasks = _read_all()
    for t in tasks:
        if t.get("id") == task_id:
            t["retries"] = t.get("retries", 0) + 1
            t["status"] = status
    _write_all(tasks)
