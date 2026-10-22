"""Curl-driven real-proxy assertions; invoked by forward_auth.sh."""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit

port = os.environ['E2E_PORT']
base = os.environ['E2E_PUBLIC_URL']
prefix = os.environ['E2E_SHAPE'] == 'prefix'
app = f'https://{"example.com" if prefix else "app.example.com"}:{port}'
api = 'http://127.0.0.1:' + os.environ['E2E_API_PORT']
work = Path(os.environ['E2E_CONFIG_DIR'])
key = {'X-Internal-Key': 'e2e-placeholder-internal-key-00000000'}


def request(url, data=None, headers=None, jar=None):
    cmd = ['curl', '--insecure', '--noproxy', '*', '-sS', '--max-time', '15', '-D', str(work / 'headers'), '-o', str(work / 'body'), '-w', '%{http_code}']
    for host in ('auth.example.com', 'app.example.com', 'example.com'):
        cmd += ['--resolve', f'{host}:{port}:127.0.0.1']
    if jar:
        cmd += ['-b', str(work / jar), '-c', str(work / jar)]
    for name, value in (headers or {}).items():
        cmd += ['-H', name + ': ' + value]
    if data is not None:
        cmd += ['-H', 'Content-Type: application/json', '--data', json.dumps(data)]
    status = int(subprocess.check_output(cmd + [url], text=True))
    response_headers = {}
    for line in (work / 'headers').read_text().splitlines()[1:]:
        if ':' in line:
            name, value = line.split(':', 1)
            response_headers[name.lower()] = value.strip()
    return status, response_headers, (work / 'body').read_text()


def admin(*args):
    subprocess.run(['docker', 'compose', '-p', 'telelogin-e2e-' + os.environ['E2E_PROXY'], '-f', 'tests/e2e/docker-compose.e2e.yml', 'exec', '-T', 'telelogin', 'python', '-m', 'src.admin', *args], check=True)


def login(username, telegram, jar):
    status, _, body = request(api + '/register', {'username': username})
    assert status == 200, body
    token = parse_qs(urlsplit(json.loads(body)['link']).query)['start'][0]
    assert request(api + '/auth/link-telegram', {'token': token, 'telegram_id': telegram}, key)[0] == 200
    status, _, body = request(base + '/sso/start', {'username': username, 'app': 'demo', 'rd': app + '/demo/x'})
    assert status == 200, body
    started = json.loads(body)
    assert request(api + '/auth/confirm-login', {'login_id': started['login_id'], 'verification_code': started['verification_code'], 'telegram_id': telegram}, key)[0] == 200
    status, headers, body = request(base + '/sso/complete', {'login_id': started['login_id']}, jar=jar)
    assert status == 200 and json.loads(body)['status'] == 'approved', body
    assert 'httponly' in headers['set-cookie'].lower()
    assert ('domain=example.com' in headers['set-cookie'].lower()) == (not prefix)


admin('app', 'add', 'demo', '--name', 'Demo')
if not prefix:
    admin('app', 'origin', 'add', 'demo', app)
original = app + '/demo/x?a=1&b=2'
status, headers, body = request(original)
assert status == 302, (status, headers, body)
location = headers['location']
assert location.startswith(base + '/login?'), location
query = parse_qs(urlsplit(location).query)
assert query['app'] == ['demo'] and query['rd'] == [original], location
assert request(app + '/demo/x', {'probe': 'unauthenticated'})[0] == 302
login('alice', 42, 'alice.cookies')
admin('app', 'allow', 'demo', 'alice')
status, _, body = request(app + '/demo/x', jar='alice.cookies')
assert status == 200 and 'X-Telelogin-User: alice' in body, (status, body)
status, _, body = request(app + '/demo/x', {'probe': 'authenticated'}, jar='alice.cookies')
assert status == 200 and 'X-Telelogin-User: alice' in body, (status, body)
status, _, body = request(app + '/demo/x', headers={'X-TeleLogin-User': 'spoof', 'X-TeleLogin-User-Id': 'spoof'}, jar='alice.cookies')
assert status == 200 and 'X-Telelogin-User: alice' in body and 'spoof' not in body, body
login('bob', 43, 'bob.cookies')
status, _, body = request(app + '/demo/x', headers={'X_TeleLogin_User': 'spoofu', 'X_TeleLogin_User_Id': 'spoofu'}, jar='alice.cookies')
assert status == 200 and 'spoofu' not in body, body
assert request(app + '/demo/x', jar='bob.cookies')[0] == 403
assert request(base + '/internal/account', {'telegram_id': 42}, key)[0] == 404
assert request(base + '/sso/logout', {}, jar='alice.cookies')[0] == 303
assert request(app + '/demo/x', jar='alice.cookies')[0] == 302
print('Redirect, cookie, identity, spoof, allowlist, internal isolation and logout checks passed')
