# Changelog

All notable changes are documented here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow semantic versioning.

## [2.0.0] - Unreleased

### Added

- Shared 30-day browser SSO sessions and forward auth for nginx, Traefik and Caddy.
- Operator CLI for apps, per-app allowlists, access policies and user invitations.
- Confidential OpenID Connect authorization code clients, PKCE S256, discovery, RS256 ID
  tokens, JWKS and opaque access tokens for userinfo.
- Image release workflow for amd64/arm64 and image-only deployment files under `deploy/`.
- Integration guide, proxy examples, Authlib example and real proxy end-to-end checks.
- Stable public user identifiers, closed registration mode and configurable cookie domains.

### Changed

- Browser login uses a shared HttpOnly session cookie; raw API and JavaScript client remain available.
- Browser sessions appear in bot session management and participate in account deletion and revocation.
- Signing keys are persisted with concurrent first-start protection and durable publication.

**Breaking changes**

- Compose publishes the API port on `127.0.0.1` only; use a reverse proxy.
- Compose defaults `FORWARDED_ALLOW_IPS` to `*` for a proxy on the host. This is safe only
  with the loopback binding or a private network restricted to trusted callers.
- `GET /` returns an HTML account page instead of JSON.
- `/login` uses the SSO cookie flow instead of storing API tokens in sessionStorage.
- `/health` now returns `{"status":"ok","version":"2.0.0"}`.

### Security

- API and SSO grants are separated; return URLs and app origins are validated per app.
- Browser POSTs enforce content types and same-origin checks; identity headers are encoded
  and proxy examples remove spoofed headers.
- OIDC codes are single-use and client-bound; replay revokes associated access tokens.
- Private RSA keys use mode 0600; cookie domain checks use an offline public suffix snapshot.

### Upgrading from 1.x

1. Stop API and bot and back up your SQLite database, environment file and data volume.
2. Review the breaking changes above. Configure HTTPS and a reverse proxy, including
   forwarded headers and blocking public access to internal endpoints. Update health-body consumers.
3. Keep `SECRET_KEY`, `INTERNAL_API_KEY`, bot credentials and your existing data volume.
   For an existing Compose installation, keep its project name and volume mapping: moving
   to `deploy/` changes the default project name and can create an empty volume. Set
   `COMPOSE_PROJECT_NAME` to the old project name or explicitly map the existing volume.
4. Copy the release environment template and transfer existing settings; set `PUBLIC_URL`,
   cookie settings and registration policy. Keep the generated OIDC key in the persistent
   data volume and include it in backups. Do not regenerate existing secrets during upgrades.
5. Set `TELELOGIN_VERSION=2.0.0`, pull the image and start API and bot. Startup applies
   idempotent schema migrations. Check `/health`, logs and a Telegram login.
6. Register apps and allow users as described in the integration guide. Update custom
   browser integrations relying on `/login` tokens to use SSO or the raw API explicitly.
   Legacy API tokens without a session id require a fresh login.

Rollback requires restoring the backup and the previous image together; do not assume
an older server supports the migrated schema.
