#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
[[ -f "${ROOT}/aws.local.env" ]] && source "${ROOT}/aws.local.env"

export AWS_PROFILE="${AWS_PROFILE:-jakshwealth}"
export AWS_REGION="${AWS_REGION:-ap-south-2}"

echo "Using AWS_PROFILE=${AWS_PROFILE} AWS_REGION=${AWS_REGION}"
aws sts get-caller-identity
