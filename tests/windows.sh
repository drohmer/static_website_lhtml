#!/bin/sh
# Runs the suites of LHTML and of the generator on a Windows machine over SSH.
#   tests/windows.sh <ssh host> [<lhtml checkout>]
# The machine needs Python 3 (`py`) and tar (Windows 10 or later); the copy
# goes to %USERPROFILE%\lhtml_windows, with its own virtual environment.
set -eu
HOST=$1
LHTML=${2:-../../lhtml/lhtml}
HERE=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export COPYFILE_DISABLE=1           # no ._* files from macOS tar
(cd "$LHTML" && git ls-files -co --exclude-standard | tar -cf "$TMP/lhtml.tar" -T - -s ',^,lhtml/,')
(cd "$HERE" && git ls-files -co --exclude-standard | grep -v -E '^\.(structure|verification)/' \
    | tar -cf "$TMP/generator.tar" -T - -s ',^,static_website_lhtml/,')
ssh "$HOST" "if not exist lhtml_windows mkdir lhtml_windows"
scp -q "$TMP/lhtml.tar" "$TMP/generator.tar" "$HOST:lhtml_windows/"
ssh "$HOST" "cd lhtml_windows && (if exist lhtml rmdir /s /q lhtml) & (if exist static_website_lhtml rmdir /s /q static_website_lhtml) & tar -xf lhtml.tar && tar -xf generator.tar && (if not exist venv py -3 -m venv venv) && venv\Scripts\python -m pip install -q -e lhtml pytest pytest-xdist -r static_website_lhtml\requirements.txt"
ssh "$HOST" "cd lhtml_windows\lhtml && ..\venv\Scripts\python -m pytest -q -p no:cacheprovider && cd ..\static_website_lhtml && ..\venv\Scripts\python -m pytest -q -p no:cacheprovider -n 8"
