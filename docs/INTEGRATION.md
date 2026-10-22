# Integrating an app with TeleLogin

TeleLogin is self-hosted: the operator owns the bot, registers trusted apps and controls access.
One Telegram confirmation creates a browser session lasting `REFRESH_TOKEN_TTL_DAYS` (30 days by
 default). Connected apps reuse it. No app consent screen is shown: register only apps you trust.

## Which mode do I need?

| Mode | Use when | Integration |
| --- | --- | --- |
| Forward auth (Mode 2) | Your app shares TeleLogin's origin or a trusted parent domain | Reverse proxy configuration; no app login code |
| OpenID Connect (Mode 1) | An app uses a standard OIDC library or an unrelated domain | Coming in a later release |
| Raw API | You need a custom login UI and token lifecycle | Existing `/register` and `/auth/*` API, [README](../README.md) |

## Mode 2: forward auth

1. Configure `PUBLIC_URL` to the externally visible TeleLogin base URL, without a trailing slash.
   Set up your bot and API as described in the README. Register a user via `POST /register` and
   follow the returned Telegram link, or invite one with
   `docker compose -f docker/docker-compose.yml exec api python -m src.admin user invite alice`.
   With `REGISTRATION_MODE=closed`, only CLI invitations create users.
2. Register your app on the server:
   ```sh
   docker compose -f docker/docker-compose.yml exec api python -m src.admin app add myapp --name 'My App'
   docker compose -f docker/docker-compose.yml exec api python -m src.admin app allow myapp alice
   ```
   Default policy is `allowlist`; each username must already exist and be linked to Telegram.
   To allow every registered, linked user instead:
   ```sh
   docker compose -f docker/docker-compose.yml exec api python -m src.admin app policy myapp all
   ```
3. Choose a deployment shape:

   | Shape | Settings | App return URLs |
   | --- | --- | --- |
   | Shared host, prefix | `PUBLIC_URL=https://example.com/telelogin`, empty `SSO_COOKIE_DOMAIN` | Same origin, e.g. `https://example.com/demo/` |
   | Own subdomain, sibling app | `PUBLIC_URL=https://auth.example.com`, `SSO_COOKIE_DOMAIN=example.com` | Register each app origin, e.g. `https://app.example.com` |

   In the sibling shape, restart API and bot with the updated settings, then run:
   ```sh
   docker compose -f docker/docker-compose.yml exec api python -m src.admin app origin add myapp https://app.example.com
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

### nginx

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

Load [dynamic.yml](../examples/traefik/dynamic.yml) through the file provider, replacing the app
upstream `echo:80`, and enable a TLS entrypoint; install your certificate/key at the shown paths. The app id is in the
forwardAuth `address` query. Set `trustForwardHeader: false`; the header-removal middleware must
run before forwardAuth. `authResponseHeaders` copies TeleLogin's verified identity into the app
request. `redirect=1` makes unauthenticated responses directly redirect browsers.

For a shared host replace its routers with [prefix.yml](../examples/traefik/prefix.yml), merging
its `telelogin-prefix` middleware into the existing middlewares map. This strips the public prefix
only on the TeleLogin router. [docker-labels.yml](../examples/traefik/docker-labels.yml) provides an
alternative Docker-provider override, including prefix instructions (same rules as dynamic.yml,
not run by the e2e test). Attach proxy, API and app to
a shared private Docker network and disable the API's published port.

### Caddy

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
  does not isolate cookies. Unrelated domains require Mode 1 in a later release.
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

Run `python -m src.admin --help` on the server (or `docker compose … exec api python -m src.admin`).
Shell access is admin access. `gen-secrets` needs no `.env` or database and prints random
`SECRET_KEY` and `INTERNAL_API_KEY` assignments. Never share them.

```text
app add ID --name NAME [--policy allowlist|all]
app list | app show ID | app remove ID
app policy ID allowlist|all
app allow ID USERNAME | app disallow ID USERNAME
app origin add|remove ID ORIGIN
user invite USERNAME | user list | user remove USERNAME
gen-secrets
```

`user invite` prints a one-use expiring Telegram link; `user remove` has the same deletion cascade
as unlink. `app remove` also removes its allowlist. No stored secret is printed.

## Mode 1: OpenID Connect

Coming in a later release. This build has no OIDC endpoints or client credentials.

## Advanced: custom UI with the raw API

The existing `/register`, `/auth/*`, `/internal/*` and JavaScript client retain their API behavior.
See the [API documentation and JS client](../README.md). Raw API clients own their login page,
number-matching polling, token storage/rotation and logout. Browser SSO cookies cannot be used as
API refresh tokens, and API tokens cannot authorize forward-auth requests.
