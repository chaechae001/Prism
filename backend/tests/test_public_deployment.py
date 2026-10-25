"""Deployment boundaries: remote reading is opt-in; editorial remains private."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api import app
from backend.app import reader_access as access
from backend.app.services import reading_modes
from backend.app.chat.providers import elice_url


def test_elice_base_and_full_endpoint_resolve_to_the_same_route():
    base = 'https://mlapi.run/00000000-0000-0000-0000-000000000001'
    expected = base + '/v1/chat/completions'
    assert elice_url(base) == expected
    assert elice_url(base + '/') == expected
    assert elice_url(expected) == expected
    assert elice_url(expected + '/') == expected
    for invalid in (base + '?key=test', base.replace('mlapi.run', 'untrusted.example'),
                    base + '/other', base.replace('https:', 'http:')):
        with pytest.raises(ValueError):
            elice_url(invalid)


def test_non_comparable_result_cannot_publish_contradictory_comparison_claims():
    draft={'items':[],'limitations':[],'relation':'different_events',
           'common_ground':[{'label':'공통점','text':'비교해서는 안 되는 주장',
                             'evidence':[{'article_id':'a','quote_id':'unknown'}]}],
           'differences':[]}
    value=reading_modes.materialize(draft,{})
    assert value['comparison']=={'relation':'different_events','common_ground':[],'differences':[]}
    assert reading_modes.checked(value,[],'perspectives').comparison.relation=='different_events'
    draft['relation']='comparable'
    with pytest.raises(ValueError):
        reading_modes.materialize(draft,{})


def test_serverless_database_returns_connections_to_the_external_pool(monkeypatch):
    from backend.app import db
    from sqlalchemy.pool import NullPool
    from unittest.mock import Mock
    monkeypatch.setattr(db, 'load_environment', lambda: None)
    for key,value in {'DB_HOST':'pooler.example','DB_PORT':'6543','DB_NAME':'test',
                      'DB_USER':'test','DB_PASSWORD':'test','DB_SSLMODE':'require','VERCEL':'1'}.items():
        monkeypatch.setenv(key,value)
    factory=Mock()
    monkeypatch.setattr(db,'create_engine',factory)
    db.get_engine.cache_clear()
    try:
        db.get_engine()
        options=factory.call_args.kwargs
        assert options['poolclass'] is NullPool
        assert options['connect_args']['prepare_threshold'] is None
        assert 'pool_size' not in options
        assert options['connect_args']['sslmode']=='require'
    finally:
        db.get_engine.cache_clear()


def request(method='GET', origin='https://prism.example'):
    return Request({'type': 'http', 'method': method, 'path': '/',
                    'headers': [(b'origin', origin.encode())],
                    'client': ('198.51.100.10', 54321),
                    'server': ('prism.example', 443), 'scheme': 'https'})


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv('CORS_ORIGINS', 'https://prism.example')
    monkeypatch.setenv('PRISM_EDITORIAL_ENABLED', '0')
    monkeypatch.delenv('PRISM_PUBLIC_READING_ENABLED', raising=False)
    access._visits.clear()
    yield
    access._visits.clear()


def test_remote_reading_is_off_by_default():
    with pytest.raises(HTTPException) as caught:
        access.reader_access(request())
    assert caught.value.status_code == 403


def test_public_reading_accepts_configured_origin_only(monkeypatch):
    monkeypatch.setenv('PRISM_PUBLIC_READING_ENABLED', '1')
    access.reading_access(request())
    with pytest.raises(HTTPException) as caught:
        access.reading_access(request(origin='https://other.example'))
    assert caught.value.status_code == 403


def test_generation_limit_does_not_block_cached_reads(monkeypatch):
    monkeypatch.setenv('PRISM_PUBLIC_READING_ENABLED', '1')
    for _ in range(6):
        access.reading_access(request('POST'))
    with pytest.raises(HTTPException) as caught:
        access.reading_access(request('POST'))
    assert caught.value.status_code == 429
    access.reading_access(request())


def test_reading_access_does_not_open_editorial_routes(monkeypatch):
    monkeypatch.setenv('PRISM_PUBLIC_READING_ENABLED', '1')
    with TestClient(app, client=('198.51.100.10', 54321)) as client:
        for path in ('/api/editorial/drafts', '/api/editorial/quality', '/api/editorial/ai/status'):
            assert client.get(path).status_code == 403


def test_remote_reading_get_preserves_response_contract(monkeypatch):
    from backend.app import reading_api
    monkeypatch.setenv('PRISM_PUBLIC_READING_ENABLED', '1')
    monkeypatch.setenv('PRISM_DATA_SOURCE', 'cluster-db')
    monkeypatch.setattr(reading_api, 'story_for', lambda identity: identity)
    monkeypatch.setattr(reading_modes, 'read', lambda story, mode: {
        'story_id': story, 'mode': mode, 'output': None, 'cached': False,
        'source_count': 1, 'model': 'test', 'prompt_version': 'test', 'notice': 'test'})
    with TestClient(app, client=('198.51.100.10', 54321)) as client:
        response = client.get('/api/local/stories/db-cluster-test/reading/easy',
                              headers={'Origin': 'https://prism.example'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'easy'
    assert response.json()['output'] is None


def test_serverless_cache_uses_explicit_writable_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('PRISM_READING_CACHE_DIR', str(tmp_path))
    assert reading_modes.location('key') == Path(tmp_path) / 'key.json'


def test_remote_dm_uses_public_switch_without_opening_accounts(monkeypatch):
    monkeypatch.setenv('PRISM_ACCOUNTS_ENABLED', '0')
    monkeypatch.setenv('PRISM_CHAT_ENABLED', '0')
    with TestClient(app, client=('198.51.100.10', 54321)) as client:
        path = '/api/social/stories/db-cluster-test/chat'
        assert client.post(path, json={'question': '핵심은?'}).status_code == 403
        monkeypatch.setenv('PRISM_PUBLIC_READING_ENABLED', '1')
        # Configuration is checked before looking up a story or calling a model.
        assert client.post(path, json={'question': '핵심은?'}).status_code == 503
