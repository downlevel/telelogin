"""Run: uvicorn app:app --host 127.0.0.1 --port 9000 (behind HTTPS in production)."""
import os

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import html

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ['SESSION_SECRET'],
                   https_only=os.getenv('COOKIE_SECURE', 'true') == 'true')
oauth = OAuth()
oauth.register('telelogin', client_id=os.environ['OIDC_CLIENT_ID'],
               client_secret=os.environ['OIDC_CLIENT_SECRET'],
               server_metadata_url=os.getenv('OIDC_ISSUER', 'https://auth.example.com') + '/.well-known/openid-configuration',
               client_kwargs={'scope': 'openid profile', 'code_challenge_method': 'S256'})


@app.get('/')
async def home(request: Request):
    user = request.session.get('user')
    if not user:
        return HTMLResponse('<a href="/login">Sign in</a>')
    return HTMLResponse('Signed in as ' + html.escape(user.get('preferred_username', user['sub'])) +
                        '<form method="post" action="/logout"><button>Log out</button></form>')


@app.get('/login')
async def login(request: Request):
    return await oauth.telelogin.authorize_redirect(request, str(request.url_for('callback')))


@app.get('/callback')
async def callback(request: Request):
    token = await oauth.telelogin.authorize_access_token(request)
    request.session['user'] = dict(token['userinfo'])
    return RedirectResponse('/', 303)


@app.post('/logout')
async def logout(request: Request):
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        return HTMLResponse('Invalid Origin', 403)
    request.session.clear()
    return RedirectResponse('/', 303)
