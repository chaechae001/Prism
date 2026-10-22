"""Read-only HTTP checks of a teammate checkout, with no real DB connection.
Usage: python scripts/reviews/check_backend_snapshot.py CHECKOUT
"""
import importlib.util
import json
from pathlib import Path
import sys
import types
from fastapi.testclient import TestClient

root = Path(sys.argv[1]).resolve()
fixture = json.loads((root / 'contracts/fixtures.json').read_text(encoding='utf-8'))['stories'][0]
package = types.ModuleType('review_backend')
package.__path__ = [str(root / 'backend/app')]
sys.modules[package.__name__] = package
repo = types.ModuleType('review_backend.news_repository')
repo.get_news_from_db = lambda story_id: fixture if story_id == fixture['id'] else None
sys.modules[repo.__name__] = repo
spec = importlib.util.spec_from_file_location('review_backend.main', root / 'backend/app/main.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = TestClient(module.app, raise_server_exceptions=False)
checks = []
for name, method, path, kwargs in [
    ('bare_list', 'get', '/api/v1/stories', {}),
    ('frontend_default_list', 'get', '/api/v1/stories?q=&mode=balanced&diversity=70&limit=6', {}),
    ('detail', 'get', '/api/v1/stories/story-001', {}),
    ('missing_detail', 'get', '/api/v1/stories/missing', {}),
    ('categories', 'get', '/api/v1/categories', {}),
    ('feedback', 'post', '/api/v1/feedback', {'json': {'story_id': 'story-001', 'kind': 'useful'}}),
    ('cors_preflight', 'options', '/api/v1/stories', {'headers': {'Origin': 'http://127.0.0.1:5173', 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'x-mock-scenario'}}),
]:
    response = getattr(client, method)(path, **kwargs)
    row = {'check': name, 'status': response.status_code, 'content_type': response.headers.get('content-type'), 'cors_allow_origin': response.headers.get('access-control-allow-origin'), 'request_id_header': bool(response.headers.get('x-request-id'))}
    if name == 'bare_list':
        data = response.json()
        row.update(total=data['total'], articles=len(data['items'][0]['story']['articles']))
    if name in ('frontend_default_list', 'missing_detail'):
        row['error'] = response.json()
        if 'error' in row['error']: row['error']['error']['request_id'] = '<per-request>'
    checks.append(row)
def database_failure(_):
    raise RuntimeError('simulated database unavailable')
module.get_news_from_db = database_failure
response = client.get('/api/v1/stories')
checks.append({'check': 'database_failure', 'status': response.status_code, 'content_type': response.headers.get('content-type'), 'body': response.text, 'request_id_header': bool(response.headers.get('x-request-id'))})
result = {'scope': 'HTTP route checks with an in-memory DB replacement. NO live DB verification.', 'checks': checks}
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
