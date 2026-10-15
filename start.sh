#!/usr/bin/env bash
# Start PlaceFinder locally: in the Ubuntu shell of WSL or in the dev
# container of a cloud-labs repository. Installs uv if needed (after asking),
# downloads the GeoNames data if it is missing and starts the server.
#
# Usage: ./start.sh [options]
#   --data NAME   GeoNames dump, e.g. cities5000 or DE (default: cities15000)
#   --port PORT   port of the server (default: 8000)
#   --prod        start uvicorn without reload and without dev tools,
#                 as on the VM in session 2 (default: fastapi dev)
#   -h, --help    show this help
# The environment variable DATA_FILE overrides --data.
set -euo pipefail

cd "$(dirname "$0")"

data=cities15000
port=8000
mode=dev
while (( $# )); do
  case "$1" in
    --data) data=${2:?--data needs a name}; shift 2 ;;
    --port) port=${2:?--port needs a number}; shift 2 ;;
    --prod) mode=prod; shift ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see ./start.sh --help)" >&2; exit 1 ;;
  esac
done

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# The repository is shared between WSL and the dev container. Their Python
# installations differ, so each gets its own virtual environment: .venv in
# the container (as everywhere in the course), a directory under ~/.cache in
# WSL. Otherwise each side would rebuild the other's environment.
if [[ -f /.dockerenv || -n "${REMOTE_CONTAINERS:-}" || -n "${COURSE_PROVIDER:-}" ]]; then
  where="dev container"
else
  where="WSL"
  export UV_PROJECT_ENVIRONMENT="${XDG_CACHE_HOME:-$HOME/.cache}/placefinder/venv"
fi

# uv: part of the dev container; in WSL installed into ~/.local/bin
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  [[ $where == WSL ]] || die "uv not found. Rebuild the dev container."
  read -r -p "uv is not installed. Install it now into ~/.local/bin? [y/N] " answer
  [[ "$answer" =~ ^[yYjJ] ]] || die "PlaceFinder needs uv: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# GeoNames data (CC BY 4.0)
if [[ -z "${DATA_FILE:-}" ]]; then
  export DATA_FILE="data/$data.txt"
  [[ -s "$DATA_FILE" ]] || data/download.sh "$data"
fi
[[ -s "$DATA_FILE" ]] || die "Data file $DATA_FILE not found."

# Stop early if the port is taken, e.g. by a server in the other environment
if ! python3 -c 'import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))' "$port" 2>/dev/null; then
  die "Port $port is in use. Stop the other server or choose another port: ./start.sh --port 8001"
fi

log "Starting PlaceFinder in $where ($mode) with $DATA_FILE"
log "Search: http://localhost:$port/places?q=Erfurt   API docs: http://localhost:$port/docs   Stop: Ctrl+C"
if [[ $mode == dev ]]; then
  exec uv run fastapi dev src/placefinder/main.py --port "$port"
else
  exec uv run --frozen --no-dev uvicorn placefinder.main:app --host 127.0.0.1 --port "$port"
fi
