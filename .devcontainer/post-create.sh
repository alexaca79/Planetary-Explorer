#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd "${script_dir}/.." && pwd)"
backend_requirements="${workspace_root}/planetary-explorer/container-app/requirements.txt"
frontend_dir="${workspace_root}/planetary-explorer/web-ui"

sudo install -d -o "$(id -u)" -g "$(id -g)" \
    /home/vscode/.azure \
    /home/vscode/.azd \
    /home/vscode/.config/gh

python3 -m venv "${VIRTUAL_ENV}"
hash -r

python -m pip config --user set global.index-url "${PIP_INDEX_URL}"
python -m pip install --upgrade pip setuptools wheel
python -m pip install \
    --requirement "${workspace_root}/requirements.txt" \
    --requirement "${backend_requirements}"

npm config set registry "${NPM_CONFIG_REGISTRY}" --location=user
npm --prefix "${frontend_dir}" ci

printf '\nPlanetary Explorer development dependencies are ready.\n'
printf 'Run: bash .devcontainer/start-local.sh\n'
printf 'Validate: bash .devcontainer/validate.sh\n'
