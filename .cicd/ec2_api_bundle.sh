#!/bin/bash
# Pack the desk and the former Lambda apps for the kite-algo-setup instances.
set -euo pipefail

ENV="${1:-dev}"
AWS_REGION="${AWS_REGION:-ap-south-2}"
case "${AWS_REGION}" in
  ap-south-2) REGION_SUFFIX="aps2" ;;
  us-east-1)  REGION_SUFFIX="use1" ;;
  *)          REGION_SUFFIX="${AWS_REGION//-/}" ;;
esac
BUCKET="jakshwealth-artifacts-${ENV}-${REGION_SUFFIX}"
KEY="kite-algo-setup/jakshwealth-api.zip"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

mkdir -p "${STAGE}/lambda"
cp -a "${WORKSPACE}/kite_app" "${STAGE}/kite_app"
cp -a "${WORKSPACE}/ec2_host" "${STAGE}/ec2_host"
cp -a "${WORKSPACE}/lambda/jw_app_config" "${STAGE}/lambda/jw_app_config"
cp -a "${WORKSPACE}/lambda/jw_secure_data" "${STAGE}/lambda/jw_secure_data"
find "${STAGE}" -type d \( -name tests -o -name __pycache__ -o -name .pytest_cache -o -name package -o -name tf-virtual-env \) -prune -exec rm -rf {} +
find "${STAGE}" -type f \( -name '*.zip' -o -name '*.pyc' \) -delete

ARCHIVE="${STAGE}/jakshwealth-api.zip"
(
  cd "${STAGE}"
  zip -qr "${ARCHIVE}" kite_app ec2_host lambda
)
aws s3 cp "${ARCHIVE}" "s3://${BUCKET}/${KEY}" --content-type application/zip
echo "Published s3://${BUCKET}/${KEY}"

aws ssm send-command \
  --document-name AWS-RunShellScript \
  --targets Key=tag:Name,Values=kite-algo-setup \
  --parameters '{"commands":["/usr/local/bin/kite-algo-setup-sync"]}' \
  --comment "Reload the kite-algo-setup API bundle" \
  || echo "No kite-algo-setup instance accepted the reload. The instance timer will pick up the bundle."
