#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f aws.local.env ]; then
  # shellcheck source=/dev/null
  source aws.local.env
fi
export AWS_PROFILE="${AWS_PROFILE:-jakshwealth}"
export AWS_REGION="${AWS_REGION:-ap-south-2}"

export ENVIRONMENT="${ENVIRONMENT:-local}"
export LOCAL_CONFIG_FILE="${LOCAL_CONFIG_FILE:-$(pwd)/config.local.json}"
export FEATURE_FLAGS_OVERRIDE_FILE="${FEATURE_FLAGS_OVERRIDE_FILE:-$(pwd)/feature_flags.local.json}"

if [ ! -f config.local.json ] && [ -f config.local.example.json ]; then
  cp config.local.example.json config.local.json
fi

if [ ! -f feature_flags.local.json ]; then
  printf '%s\n' '{}' > feature_flags.local.json
fi

# --header-map dangerous: required for custom headers with underscores (auth_code, refresh_token, etc.)
exec python -m gunicorn -b "0.0.0.0:${PORT:-3000}" --workers 1 --header-map dangerous --capture-output serve:app
