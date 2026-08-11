#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
backend_dir="${workspace_root}/planetary-explorer/container-app"
frontend_dir="${workspace_root}/planetary-explorer/web-ui"
infra_file="${workspace_root}/planetary-explorer/infra/main.bicep"
temp_dir="$(mktemp -d)"
backend_pid=""
frontend_pid=""

cleanup() {
    for pid in "${backend_pid}" "${frontend_pid}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}"
        fi
    done
    wait "${backend_pid}" "${frontend_pid}" 2>/dev/null || true
    rm -rf "${temp_dir}"
}
trap cleanup EXIT INT TERM

wait_for_url() {
    local name="$1"
    local url="$2"
    local log_file="$3"

    for _ in $(seq 1 90); do
        if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done

    printf '%s did not become ready at %s\n' "${name}" "${url}" >&2
    cat "${log_file}" >&2
    return 1
}

for command_name in az azd docker gh git node npm pwsh python; do
    command -v "${command_name}" >/dev/null
done

python --version
node --version
npm --version
git --version
gh --version
az version --output table
azd version
pwsh --version
docker --version

test "${PIP_INDEX_URL}" = "https://packagefeedproxy.microsoft.io/pypi/simple"
test "$(python -m pip config get global.index-url)" = "${PIP_INDEX_URL}"
test "${NPM_CONFIG_REGISTRY}" = "https://packagefeedproxy.microsoft.io/npm/"
test "$(npm config get registry)" = "${NPM_CONFIG_REGISTRY}"
test "${YARN_NPM_REGISTRY_SERVER}" = "https://packagefeedproxy.microsoft.io/npm/"
test "${NUGET_CFS_SOURCE}" = "https://packagefeedproxy.microsoft.io/nuget/v3/index.json"
grep --fixed-strings "${NUGET_CFS_SOURCE}" /home/vscode/.nuget/NuGet/NuGet.Config >/dev/null

(
    cd "${backend_dir}"
    DISABLE_AUTH=true RESILIENCE_FORCE_SEED=1 \
        python -m pytest \
            tests/test_collection_index.py \
            tests/test_contracts.py \
            tests/test_public_stac_adapter.py
)

npm --prefix "${frontend_dir}" run test:run -- \
    src/components/__tests__/TerrainWorkflow.test.tsx \
    src/components/trace/__tests__/ConfirmationCard.test.tsx
npm --prefix "${frontend_dir}" run build

az bicep build --file "${infra_file}" --stdout >/dev/null

(
    cd "${backend_dir}"
    DISABLE_AUTH=true \
    RESILIENCE_FORCE_SEED=1 \
    CORS_ORIGINS=http://localhost:5173 \
        exec python -m uvicorn fastapi_app:app \
            --host 0.0.0.0 \
            --port 8000
) >"${temp_dir}/backend.log" 2>&1 &
backend_pid=$!

wait_for_url \
    "Backend" \
    "http://127.0.0.1:8000/api/config" \
    "${temp_dir}/backend.log"

curl --fail --silent --show-error "http://127.0.0.1:8000/api/config" \
    | python -c 'import json, sys; assert json.load(sys.stdin)["features"]["mpcPublic"] is True'

health_status="$(
    curl --silent --show-error \
        --output "${temp_dir}/health.json" \
        --write-out '%{http_code}' \
        "http://127.0.0.1:8000/api/health"
)"
if [[ "${health_status}" != "200" && "${health_status}" != "503" ]]; then
    cat "${temp_dir}/health.json" >&2
    printf 'Unexpected backend health status: %s\n' "${health_status}" >&2
    exit 1
fi
python -c 'import json, sys; assert json.load(open(sys.argv[1], encoding="utf-8"))["status"] in {"healthy", "degraded"}' \
    "${temp_dir}/health.json"

(
    cd "${frontend_dir}"
    exec ./node_modules/.bin/vite \
        --host 0.0.0.0 \
        --port 5173 \
        --strictPort
) >"${temp_dir}/frontend.log" 2>&1 &
frontend_pid=$!

wait_for_url \
    "Frontend" \
    "http://127.0.0.1:5173" \
    "${temp_dir}/frontend.log"

printf '\nValidation passed without provisioning Azure resources.\n'
