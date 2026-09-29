#!/usr/bin/env bash

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$root/.venv/bin/python" "$root/DM.py" "$@"
