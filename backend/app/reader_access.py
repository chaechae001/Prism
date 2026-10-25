"""Explicit public reading access; editorial writes remain loopback-only."""
import os
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request
from .account_auth import check_origin

_visits = defaultdict(deque)
_lock = Lock()


def public_reading_enabled():
    return os.getenv('PRISM_PUBLIC_READING_ENABLED') == '1'


def reader_access(request: Request):
    if not public_reading_enabled() and (
        not request.client or request.client.host not in {'127.0.0.1', '::1', 'testclient'}
    ):
        raise HTTPException(403, '현재 환경에서는 읽기 기능에 접근할 수 없습니다.')
    check_origin(request)
    if public_reading_enabled() and request.method == 'POST':
        # A small per-worker limit supplements provider quotas. It is deliberately
        # conservative and is not a distributed billing or authentication system.
        now = monotonic()
        with _lock:
            visits = _visits['generation']
            while visits and visits[0] <= now - 60:
                visits.popleft()
            if len(visits) >= 6:
                raise HTTPException(429, '분석 요청이 많습니다. 1분 후 다시 시도해주세요.')
            visits.append(now)


def reading_access(request: Request):
    if public_reading_enabled():
        reader_access(request)
    else:
        from .editorial_api import local_editor
        local_editor(request)
