#!/bin/sh
set -eu

xbotgo_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$xbotgo_source/install.py"
