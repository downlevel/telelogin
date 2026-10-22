# Contributing

Use Python 3.11+ and Node.js for the JavaScript client checks. From the checkout root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
```

Configure the local bot credentials and secrets in `.env`. For development run
`.venv/bin/uvicorn src.app:app` and `.venv/bin/python -m src.bot` in separate terminals.

Run the proof command before submitting a PR:

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check src tests && .venv/bin/python -W error::DeprecationWarning -m pytest -q
```

With Docker available, run each real proxy check:

```bash
tests/e2e/forward_auth.sh nginx
tests/e2e/forward_auth.sh traefik
tests/e2e/forward_auth.sh caddy
```

Preserve existing line endings: Python under `src/` and `tests/`, `docker/*.yml` and
`docker/env.example` use CRLF. Markdown, workflow YAML, shell scripts, proxy examples and
new `deploy/` files use LF. Follow `.gitattributes`; avoid whole-file newline churn.

PRs should describe the concrete problem, resulting behavior, relevant tests and any
limitations. Include regression coverage for behavior changes and update affected examples
and documentation. Never commit secrets, runtime databases or private keys. Maintainers
publish releases by tagging; a normal branch or PR does not run the release workflow.
Stable semantic version tags update `latest`; prerelease tags (for example `v2.1.0-rc.1`)
publish their version tag without moving `latest`.
