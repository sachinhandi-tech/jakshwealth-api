#!/bin/bash
# Package a self-contained JakshWealth Lambda zip (no shared layers).
# Usage: lambda_package.sh <lambda-directory>

set -e

lambda_dir="${1:?lambda directory required}"
cd "$lambda_dir"

LAMBDA_NAME=$(basename "$(pwd)")

tf-update() {
    pip install --upgrade pip
    pip install -r requirements.txt
}

tf-genupload() {
    local current
    current=$(pwd)

    deactivate 2>/dev/null || true

    if [ ! -d "tf-virtual-env" ]; then
        python3 -m venv tf-virtual-env
    fi

    # shellcheck disable=SC1091
    source tf-virtual-env/bin/activate
    tf-update

    rm -rf package
    mkdir package
    cp ./*.py package/
    for dir in */; do
        case "$dir" in
            tests/|package/|tf-virtual-env/|__pycache__/|.pytest_cache/|certs/) continue ;;
        esac
        cp -R "${dir%/}" package/
    done

    # Corporate CA bundle for deployed TLS (e.g. DATABRICKS_TLS_TRUSTED_CA_FILE=/var/task/certs/corp-ca.pem).
    if [ -f "certs/corp-ca.pem" ]; then
        mkdir -p package/certs
        cp certs/corp-ca.pem package/certs/corp-ca.pem
    fi

    pip install -r requirements.txt -t package/

    cd package || exit 1
    rm -rf pip* pkg_resources *pycache* pylint* setuptools* 2>/dev/null || true
    rm -f "../${LAMBDA_NAME}.zip"
    zip -r -X "../${LAMBDA_NAME}.zip" .
    cd ..
    rm -rf package

    echo "Done, ${current}/${LAMBDA_NAME}.zip ready to upload."
}

tf-genupload
