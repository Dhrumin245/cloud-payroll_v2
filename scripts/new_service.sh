#!/usr/bin/env bash
# Usage: scripts/new_service.sh <service-name>     e.g. scripts/new_service.sh auth-service
# Copies services/_template to services/<service-name> and sets its default service name.
set -euo pipefail
NAME="${1:?usage: new_service.sh <service-name>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/services/$NAME"
[ -e "$DEST" ] && { echo "$DEST already exists"; exit 1; }
cp -r "$ROOT/services/_template" "$DEST"
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$DEST/.pytest_cache" "$DEST/.coverage" "$DEST/.ruff_cache"
sed -i "s/service_name: str = \"template\"/service_name: str = \"$NAME\"/" "$DEST/app/config.py"
# shellcheck disable=SC2016  # the backticks are literal Markdown, not command substitution
printf '# %s\n\nCreated from `services/_template`. See `docs/api-contract.md` for this service'"'"'s endpoints.\n' "$NAME" > "$DEST/README.md"
echo "Created $DEST"
