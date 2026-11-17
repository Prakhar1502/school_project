#!/bin/sh
# School Fee Register - start on Mac or Linux
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then exec python3 server.py "$@"; fi
if command -v python >/dev/null 2>&1; then exec python server.py "$@"; fi
echo "Python 3 is not installed. Get it from https://www.python.org/downloads/"
