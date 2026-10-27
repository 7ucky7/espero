#!/usr/bin/env bash
# Point git at the repo's hooks (no copy step, so hooks stay versioned).
set -euo pipefail
cd "$(dirname "$0")/.."
chmod +x .githooks/pre-push scripts/check.sh
git config core.hooksPath .githooks
echo "installed: core.hooksPath -> .githooks"
echo "every push now runs ./scripts/check.sh (bypass once with: git push --no-verify)"
