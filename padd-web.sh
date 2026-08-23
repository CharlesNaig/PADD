#!/usr/bin/env sh

# Launch PADD Web with Python's standard library. Extra options are forwarded,
# for example: ./padd-web.sh --host 0.0.0.0 --port 8080
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "${script_dir}"
exec python3 -m padd_web.server "$@"

