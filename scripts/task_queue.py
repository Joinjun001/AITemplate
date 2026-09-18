#!/usr/bin/env python3
"""tasks/queue.jsonl (JSONL: 한 줄에 JSON 객체 하나) 조작 헬퍼.

이름을 queue.py가 아니라 task_queue.py로 지은 이유: Python 표준 라이브러리에
이미 'queue' 모듈이 있어서, 같은 이름으로 만들면 sys.path 우선순위에 따라
표준 라이브러리를 가려버릴 수 있기 때문입니다.
"""
from __future__ import annotations

import json
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
