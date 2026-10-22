#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
proxy=${1:?Usage: tests/e2e/forward_auth.sh nginx|traefik|caddy}
case "$proxy" in nginx|traefik|caddy) ;; *) echo 'Unknown proxy' >&2; exit 2 ;; esac
export E2E_PORT=${E2E_PORT:-18080} E2E_API_PORT=${E2E_API_PORT:-18000}
export E2E_CONFIG_DIR
E2E_CONFIG_DIR=$(mktemp -d "$PWD/tests/e2e/.run-XXXXXX")
compose=(docker compose -p "telelogin-e2e-$proxy" -f tests/e2e/docker-compose.e2e.yml --profile "$proxy")
cleanup() {
    result=$?
    if ((result)); then "${compose[@]}" logs --no-color || true; fi
    "${compose[@]}" down -v --remove-orphans || true
    rm -rf "$E2E_CONFIG_DIR"
}
trap cleanup EXIT
shapes=(prefix subdomain)
for shape in "${shapes[@]}"; do
    export E2E_SHAPE=$shape E2E_PROXY=$proxy
    if [[ $shape == prefix ]]; then
        export E2E_PUBLIC_URL="https://example.com:$E2E_PORT/telelogin" E2E_COOKIE_DOMAIN=''
    else
        export E2E_PUBLIC_URL="https://auth.example.com:$E2E_PORT" E2E_COOKIE_DOMAIN=example.com
    fi
    # Use shipped TLS configurations and the public test certificate. Only
    # app id and upstreams change; the auth directives are not rewritten.
    python3 - <<'PY'
import os
from pathlib import Path
out = Path(os.environ['E2E_CONFIG_DIR'])
proxy, shape = os.environ['E2E_PROXY'], os.environ['E2E_SHAPE']
if proxy == 'nginx':
    for source, target in [(shape + '.conf', 'nginx.conf'), ('telelogin.conf', 'telelogin.conf'), ('protect-app.conf', 'protect-app.conf')]:
        text = Path('examples/nginx', source).read_text().replace('127.0.0.1:8000', 'telelogin:8000').replace('127.0.0.1:9000', 'echo:80').replace('myapp', 'demo')
        (out / target).write_text(text)
elif proxy == 'traefik':
    text = Path('examples/traefik/dynamic.yml').read_text()
    if shape == 'prefix':
        # Merge the shipped prefix routers/middleware with the shared auth
        # middleware, services and TLS settings; no auth directives change.
        prefix = Path('examples/traefik/prefix.yml').read_text()
        routers, prefix_middlewares = prefix.split('  middlewares:\n', 1)
        _, shared = text.split('  middlewares:\n', 1)
        middlewares, services = shared.split('  services:\n', 1)
        text = routers + '  middlewares:\n' + middlewares + prefix_middlewares + '  services:\n' + services
    (out / 'dynamic.yml').write_text(text.replace('myapp', 'demo'))
else:
    text = Path('examples/caddy', 'prefix.Caddyfile' if shape == 'prefix' else 'Caddyfile').read_text().replace('myapp', 'demo')
    (out / 'Caddyfile').write_text(text)
PY
    "${compose[@]}" up -d --build "$proxy"
    api_ready=false
    for attempt in {1..60}; do
        if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS "http://127.0.0.1:$E2E_API_PORT/health" >/dev/null 2>&1; then
            api_ready=true
            break
        fi
        sleep 1
    done
    if [[ $api_ready != true ]]; then
        echo "API did not become ready ($proxy $shape)" >&2
        exit 1
    fi
    app_host=app.example.com
    if [[ $shape == prefix ]]; then app_host=example.com; fi
    proxy_ready=false
    for attempt in {1..60}; do
        status=$(curl --noproxy '*' --insecure --connect-timeout 1 --max-time 2 -sS -o /dev/null -w '%{http_code}' \
            --resolve "$app_host:$E2E_PORT:127.0.0.1" "https://$app_host:$E2E_PORT/demo/x" 2>/dev/null) || status=000
        if [[ $status == 302 || $status == 401 ]]; then
            proxy_ready=true
            break
        fi
        sleep 1
    done
    if [[ $proxy_ready != true ]]; then
        echo "Proxy did not become ready ($proxy $shape; last HTTP status $status)" >&2
        exit 1
    fi
    python3 tests/e2e/check_forward_auth.py
    "${compose[@]}" down -v --remove-orphans
    echo "PASS: $proxy $shape"
done
