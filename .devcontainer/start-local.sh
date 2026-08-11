#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
backend_dir="${workspace_root}/planetary-explorer/container-app"
frontend_dir="${workspace_root}/planetary-explorer/web-ui"
backend_port="${BACKEND_PORT:-8000}"
frontend_port="${FRONTEND_PORT:-5173}"
backend_pid=""
frontend_pid=""

# shellcheck disable=SC2317  # Invoked indirectly by trap.
cleanup() {
    for pid in "${backend_pid}" "${frontend_pid}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}"
        fi
    done
    wait "${backend_pid}" "${frontend_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

export DISABLE_AUTH="${DISABLE_AUTH:-true}"
export RESILIENCE_FORCE_SEED="${RESILIENCE_FORCE_SEED:-1}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:${frontend_port}}"

(
    cd "${backend_dir}"
    exec python -m uvicorn fastapi_app:app \
        --reload \
        --host 0.0.0.0 \
        --port "${backend_port}"
) &
backend_pid=$!

(
    cd "${frontend_dir}"
    exec ./node_modules/.bin/vite \
        --host 0.0.0.0 \
        --port "${frontend_port}" \
        --strictPort
) &
frontend_pid=$!

printf 'Backend: http://localhost:%s/api/config\n' "${backend_port}"
printf 'Frontend: http://localhost:%s\n' "${frontend_port}"

set +e
wait -n "${backend_pid}" "${frontend_pid}"
status=$?
set -e
exit "${status}"
