# Integrating an app with TeleLogin

TeleLogin is self-hosted: the operator owns the bot, registers trusted apps and controls access.
One Telegram confirmation creates a browser session lasting `REFRESH_TOKEN_TTL_DAYS` (30 days by
 default). Connected apps reuse it. No app consent screen is shown: register only apps you trust.

## Which mode do I need?

| Mode | Use when | Integration |
| --- | --- | --- |
| Forward auth (Mode 2) | Your app shares TeleLogin's origin or a trusted parent domain | Reverse proxy configuration; no app login code |
| OpenID Connect (Mode 1) | An app uses a standard OIDC library or an unrelated domain | Confidential clients; standard OIDC library |
| Raw API | You need a custom login UI and token lifecycle | Existing `/register` and `/auth/*` API, [README](../README.md) |

All Compose commands below use the release installation in `deploy/`, run from the checkout
root. Developers using `docker/` substitute `docker/docker-compose.yml` for that path.

## Mode 2: forward auth

1. Configure `PUBLIC_URL` to the externally visible TeleLogin base URL, without a trailing slash.
   Set up your bot and API as described in the README. Register a user via `POST /register` and
   follow the returned Telegram link, or invite one with
   `docker compose -f deploy/docker-compose.yml exec api python -m src.admin user invite alice`.
   With `REGISTRATION_MODE=closed`, only CLI invitations create users.
2. Register your app on the server:
   ```sh
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app add myapp --name 'My App'
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app allow myapp alice
   ```
   Default policy is `allowlist`; each username must already exist and be linked to Telegram.
   To allow every registered, linked user instead:
   ```sh
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app policy myapp all
   ```
3. Choose a deployment shape:

   | Shape | Settings | App return URLs |
   | --- | --- | --- |
   | Shared host, prefix | `PUBLIC_URL=https://example.com/telelogin`, empty `SSO_COOKIE_DOMAIN` | Same origin, e.g. `https://example.com/demo/` |
   | Own subdomain, sibling app | `PUBLIC_URL=https://auth.example.com`, `SSO_COOKIE_DOMAIN=example.com` | Register each app origin, e.g. `https://app.example.com` |

   In the sibling shape, restart API and bot with the updated settings, then run:
   ```sh
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app origin add myapp https://app.example.com
   ```
   The origin must receive the configured cookie. Origins have no path, query or fragment. HTTPS
   is required except localhost/127.0.0.1 development. Cookie domains must be a non-public parent
   of the public host: `co.uk`, `github.io`, IPs and leading dots are rejected. Validation uses an
   offline bundled Public Suffix List, including private suffixes.
4. Install a proxy configuration from the examples below. Replace hostnames, upstreams and `myapp`
   with your values. The proxy strips `/telelogin` for the prefix shape: API routes remain at `/`.
   Every generated absolute link uses `PUBLIC_URL`; browser fetches are prefix-relative.
5. Read `X-TeleLogin-User` in your app. It is UTF-8 percent-encoded; URL-decode it with e.g.
   `urllib.parse.unquote(value)` in Python. `X-TeleLogin-User-Id` is the stable UUID identity.
   Unicode, spaces, percent signs and control characters remain safe in the ASCII header.
6. Link to `PUBLIC_URL/logout?app=myapp&rd=<URL-encoded destination>`. GET only asks for
   confirmation; POST revokes the browser session and clears its cookie. Other connected apps
   require a new confirmation on their next protected request.

## Proxy examples

These configs target **nginx 1.29**, **Traefik v3.5**, and **Caddy 2.10**. The real-proxy harness is
`tests/e2e/forward_auth.sh nginx|traefik|caddy`. Run each separately from the repository root with
Docker Compose, bash, curl and python3. It builds the API locally and uses disposable containers.
It uses the shipped TLS configs with only app-id/upstream substitutions and a checked-in public
self-signed test certificate (`curl --insecure` only in the harness).
All three proxies cover both the prefix and sibling-subdomain shapes. No real bot is needed.
Local ports default to 18080 (proxy) and 18000 (internal test API); override `E2E_PORT` and
`E2E_API_PORT` if necessary. The API test port is bound to loopback and removed afterward.

### Docker proxy networking

For a proxy on the host, keep the base Compose file and its loopback port binding.
For a proxy in Docker, remove the published API port with the shipped override (Docker
Compose 2.24.0+ is required for `!reset`):

```sh
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.docker-proxy.yml up -d
```

Use both `-f` arguments on subsequent `up` commands so the port stays unpublished.
With the default project name `deploy`, the network is `deploy_telelogin_network`; if you
set `COMPOSE_PROJECT_NAME` or `-p`, replace `deploy` with that project name. The API has
network alias `telelogin`. The development project's default network is `docker_telelogin_network`.

In the proxy's separate Compose file, attach its service to that existing network (merge
this into the proxy's configuration; retain any other networks it needs):

```yaml
services:
  proxy:
    networks:
      - telelogin
networks:
  telelogin:
    external: true
    name: deploy_telelogin_network
```

Start TeleLogin first so the network exists. Alternatively, for an already running proxy
container named `caddy`, attach it with:

```sh
docker network connect deploy_telelogin_network caddy
```

Replace `caddy` with your actual proxy container name; a manual attachment must be repeated
if that container is recreated. Attach the protected app to a network reachable by the proxy
as well, and replace the example app upstream separately. Only trusted containers may join
the TeleLogin network when `FORWARDED_ALLOW_IPS=*` is used.

The Caddy and Traefik examples already use `telelogin:8000`. For host proxies replace that
TeleLogin upstream everywhere with `127.0.0.1:8000` (or your `API_PORT`). The nginx examples
use the host upstream; for Docker replace every TeleLogin `127.0.0.1:8000` upstream with
`telelogin:8000`. Preserve URL paths and trailing slashes when replacing upstreams.

### nginx

Host proxy → `127.0.0.1:8000` (replace `8000` with `API_PORT`); proxy in Docker → `telelogin:8000` after joining the TeleLogin Compose network (`deploy_telelogin_network` by default). See [Docker proxy networking](#docker-proxy-networking) for the network attachment and port-removal override.

For a shared host, copy [telelogin.conf](../examples/nginx/telelogin.conf) and
[protect-app.conf](../examples/nginx/protect-app.conf) into `/etc/nginx/`, then adapt the
[prefix server](../examples/nginx/prefix.conf). For sibling subdomains use
[subdomain.conf](../examples/nginx/subdomain.conf) and the same `protect-app.conf`.
The app id is `set $telelogin_app myapp` in the protection snippet, included inside the app location.
Install your own TLS certificate/key at the paths shown in the server blocks. The app upstream placeholder is `127.0.0.1:9000`.

nginx uses `auth_request`: 401 becomes a 302 via `X-TeleLogin-Login` and a named location.
TeleLogin has already encoded that login URL. The snippet overwrites both identity headers and
blocks public access to `/internal/*`. Keep the verify location `internal`.

### Traefik

Host proxy → `127.0.0.1:8000` (replace `8000` with `API_PORT`); proxy in Docker → `telelogin:8000` after joining the TeleLogin Compose network (`deploy_telelogin_network` by default). See [Docker proxy networking](#docker-proxy-networking) for the network attachment and port-removal override.

Load [dynamic.yml](../examples/traefik/dynamic.yml) through the file provider, replacing the app
upstream `echo:80`, and enable a TLS entrypoint; install your certificate/key at the shown paths. The app id is in the
forwardAuth `address` query. Set `trustForwardHeader: false`; the header-removal middleware must
run before forwardAuth. `authResponseHeaders` copies TeleLogin's verified identity into the app
request. `redirect=1` makes unauthenticated responses directly redirect browsers.

For a shared host replace its routers with [prefix.yml](../examples/traefik/prefix.yml), merging
its `telelogin-prefix` middleware into the existing middlewares map. This strips the public prefix
only on the TeleLogin router. [docker-labels.yml](../examples/traefik/docker-labels.yml) provides an
alternative Docker-provider override, including prefix instructions (same rules as dynamic.yml,
not run by the e2e test).

### Caddy

Host proxy → `127.0.0.1:8000` (replace `8000` with `API_PORT`); proxy in Docker → `telelogin:8000` after joining the TeleLogin Compose network (`deploy_telelogin_network` by default). See [Docker proxy networking](#docker-proxy-networking) for the network attachment and port-removal override.

Adapt [Caddyfile](../examples/caddy/Caddyfile) for sibling subdomains, or
[prefix.Caddyfile](../examples/caddy/prefix.Caddyfile) for a shared host. Install your certificate/key at the paths shown (or replace the `tls` directive with your
normal Caddy certificate automation). The app id is the `app=myapp` query in `forward_auth`'s `uri`. The `route` block
preserves header-removal-before-auth ordering, then `copy_headers` supplies the verified identity.
`handle_path /telelogin/*` strips the prefix in the shared-host shape.

## Security and operation

- Trust `X-TeleLogin-*` identity headers only from your proxy. The app must be reachable only
  through that proxy; every configuration overwrites or strips client-supplied identity headers, including the
  underscore variants (`X_TeleLogin_User`), because some app servers (CGI/FastCGI such as PHP-FPM,
  some WSGI servers) treat `_` and `-` as the same header name.
- `SSO_COOKIE_DOMAIN` shares the browser credential with **every subdomain** of that domain.
  Use it only when all subdomains are trusted. A registered app origin controls redirects; it
  does not isolate cookies. Unrelated domains require Mode 1.
- Keep `SSO_COOKIE_SECURE=true` for HTTPS. Set false only for plain HTTP local development.
  Cookies are HttpOnly, SameSite=Lax, Path=/; empty domain means host-only. Browser POST endpoints
  require JSON (logout also accepts form data) and reject an Origin other than `PUBLIC_URL`'s
  origin. Raw API CORS settings do not enable CORS on `/sso/*`.
- The development Compose API port is now **127.0.0.1:${API_PORT:-8000}**, a breaking deployment
  change. A proxy on the host reaches the container from the Docker gateway address (e.g.
  172.17.0.1), not 127.0.0.1, so a `127.0.0.1` value never matches and every visitor would share
  one IP for rate limits and Telegram confirmations; the Compose default is therefore
  `FORWARDED_ALLOW_IPS='*'`, safe only while the port is published on 127.0.0.1. Docker proxies should remove published ports and use a private shared network;
  set `FORWARDED_ALLOW_IPS` to that network's range, or `*` only when nothing else can reach the
  container. Proxies must set `X-Forwarded-For`. Never expose `/internal/*` publicly.
- `/sso/verify` returns 200 with identity for allowed users, 401 (or 302 with `redirect=1`) for
  missing/revoked/expired sessions, and 403 for authenticated users without app access. Header
  `X-TeleLogin-App` and query `app` must agree when both are sent. All responses are `no-store`.
- Revoke sessions using the bot's `/sessions` (`browser` versus `app/API`) or revoke-all controls.
  `/auth/logout-all` revokes both kinds. Unlink/delete removes the account, sessions and allowlist
  memberships. Return URLs are app-scoped and default to `PUBLIC_URL/` if invalid.

## Operator CLI

Run `docker compose -f deploy/docker-compose.yml exec api python -m src.admin --help`.
Prefix the subcommands below with `docker compose -f deploy/docker-compose.yml exec api python -m src.admin`.
Shell access is admin access. `gen-secrets` needs no `.env` or database and prints random
`SECRET_KEY` and `INTERNAL_API_KEY` assignments. Never share them.

```text
app add ID --name NAME [--policy allowlist|all] [--redirect-uri URI ...]
app list | app show ID | app remove ID
app policy ID allowlist|all
app allow ID USERNAME | app disallow ID USERNAME
app origin add|remove ID ORIGIN
app redirect-uri add|remove ID URI
app rotate-secret ID
user invite USERNAME | user list | user remove USERNAME
gen-secrets
```

`user invite` prints a one-use expiring Telegram link; `user remove` has the same deletion cascade
as unlink. `app remove` also removes its allowlist. No stored secret is printed.

## Mode 1: OpenID Connect

Use Mode 1 for apps on unrelated domains or apps with a standard OIDC client library.
The operator trusts every registered app; there is no consent screen.

1. Register a confidential client and its exact callback URL:

   ```sh
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app add myapp --name "My App" --redirect-uri https://app.example.com/callback
   docker compose -f deploy/docker-compose.yml exec api python -m src.admin app allow myapp alice
   ```

   Save the printed client secret: it is shown once and only its SHA-256 hash is stored.
   Repeat `--redirect-uri` for additional callback URLs. Alternatively use
   `app redirect-uri add myapp URI`; adding the first URI generates a secret if needed.
   `app rotate-secret myapp` replaces the secret immediately; update the app configuration.
   Redirect URIs must use HTTPS, except HTTP on localhost/127.0.0.1 for development; fragments
   and credentials are forbidden. Matching is exact, including path and query.
   To admit every linked user instead, run `app policy myapp all`.
2. Configure your OIDC library:

   | Setting | Value |
   |---|---|
   | Issuer | Your `PUBLIC_URL`, e.g. `https://auth.example.com` |
   | Discovery URL | `PUBLIC_URL/.well-known/openid-configuration` |
   | Client ID | `myapp` |
   | Client secret | The value printed by the CLI |
   | Scopes | `openid profile` |
   | Redirect URI | The exact registered callback URL |
   | Flow | Authorization code; PKCE S256 recommended |
   | Client authentication | `client_secret_basic` or `client_secret_post` |

   With a path prefix, issuer is e.g. `https://example.com/telelogin` and discovery is
   `https://example.com/telelogin/.well-known/openid-configuration`. Keep that prefix in all URLs.
3. Use the [Authlib FastAPI example](../examples/oidc_fastapi/app.py): install its
   `requirements.txt`, set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and a random
   `SESSION_SECRET`, then run `uvicorn app:app --host 127.0.0.1 --port 9000` from that directory.
   Register the public `/callback` URL first. Put it behind an HTTPS proxy; for plain HTTP
   local development only, set `COOKIE_SECURE=false`. The example stores identity in a signed
   session cookie and its logout clears that app session. It does not store bearer tokens in
   the cookie. A typical Authlib registration is:

   ```python
   oauth.register(
       "telelogin", client_id=client_id, client_secret=client_secret,
       server_metadata_url=issuer + "/.well-known/openid-configuration",
       client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"},
   )
   ```

The stable UUID `sub` identifies the user. `profile` adds `preferred_username` and `name`.
ID tokens are signed with RS256 and a public key from `/jwks.json`; access tokens are opaque,
last 10 minutes by default, and work only at `/userinfo`. Raw API HS256 tokens and OIDC tokens
are mutually unusable. Codes are single use; replay revokes the access tokens issued from that
code. Removing app access also prevents `/userinfo` and code redemption.

Only confidential clients with a backend and a secret are supported. Browser-only SPAs should
use Mode 2 or a small backend. There are no OIDC refresh tokens, dynamic registration, consent
screens, RP-initiated logout, or back-channel logout. `max_age`, `claims`, and `ui_locales` are
unsupported and ignored. `prompt=none` fails with `login_required` without a browser session;
`prompt=login` forces a new Telegram confirmation. Otherwise the browser session is reused.
Revoking a TeleLogin browser session blocks new codes and unredeemed codes. It does not end
sessions that an OIDC app has created itself; already issued OIDC access tokens last until expiry
unless replayed or app access is removed. Unlink and user/app removal delete associated grants.

The API generates `OIDC_KEY_FILE` on first startup with mode 0600. Persist this file alongside
SQLite data and keep it private. For manual key rotation: stop the API, back up the old key
securely, remove the key file, and restart to generate a new one. Existing ID tokens stop
validating after clients refresh their JWKS cache; coordinate app reauthentication and cache
refresh with the rotation. Automated rotation and overlapping signing keys are unsupported.

## Advanced: custom UI with the raw API

The existing `/register`, `/auth/*`, `/internal/*` and JavaScript client retain their API behavior.
See the [API documentation and JS client](../README.md). Raw API clients own their login page,
number-matching polling, token storage/rotation and logout. Browser SSO cookies cannot be used as
API refresh tokens, and API tokens cannot authorize forward-auth requests.

### Running the Authlib example behind a proxy

Set `APP_ORIGIN` to the app's external origin (`scheme://host[:port]`, no path or
trailing slash), for example `https://app.example.com`. Logout compares the browser
Origin against this value; when unset it uses the origin part of `request.base_url`.
Behind a trusted reverse proxy, start uvicorn with `--proxy-headers
--forwarded-allow-ips <trusted-proxy-addresses>` so callback URLs use the external
scheme. Configure the proxy to preserve the external Host and set forwarded headers.
Never trust forwarded headers from arbitrary public callers.
