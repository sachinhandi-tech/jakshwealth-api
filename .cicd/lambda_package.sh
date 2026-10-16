#!/bin/bash
# Package a self-contained JakshWealth Lambda zip (no shared layers).
# Usage: lambda_package.sh <lambda-directory>

set -e

lambda_dir="${1:?lambda directory required}"
cd "$lambda_dir"

LAMBDA_NAME=$(basename "$(pwd)")
# Must match automation_codes/terraforms/lambda.tf runtime (python3.12).
LAMBDA_PYTHON_VERSION="${LAMBDA_PYTHON_VERSION:-3.12}"
LAMBDA_PLATFORM="${LAMBDA_PLATFORM:-manylinux2014_x86_64}"

resolve_python_bin() {
    if [ -n "${PYTHON_BIN:-}" ] && command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        echo "${PYTHON_BIN}"
        return 0
    fi
    if command -v "python${LAMBDA_PYTHON_VERSION}" >/dev/null 2>&1; then
        echo "python${LAMBDA_PYTHON_VERSION}"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        echo python3
        return 0
    fi
    echo "ERROR: no Python interpreter found (need python${LAMBDA_PYTHON_VERSION} or python3)" >&2
    exit 1
}

tf-update() {
    pip install --upgrade pip
    pip install -r requirements.txt
}

install_lambda_deps() {
    # Cross-build Linux cp312 wheels so Jenkins/macOS hosts match Lambda (Amazon Linux, Python 3.12).
    pip install -r requirements.txt -t package/ \
        --platform "${LAMBDA_PLATFORM}" \
        --python-version "${LAMBDA_PYTHON_VERSION}" \
        --implementation cp \
        --only-binary=:all: \
        --upgrade
}

tf-genupload() {
    local current
    local python_bin
    current=$(pwd)
    python_bin="$(resolve_python_bin)"

    deactivate 2>/dev/null || true

    if [ ! -d "tf-virtual-env" ]; then
        "${python_bin}" -m venv tf-virtual-env
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

    install_lambda_deps

    cd package || exit 1
    rm -rf pip* pkg_resources *pycache* pylint* setuptools* 2>/dev/null || true
    rm -f "../${LAMBDA_NAME}.zip"
    zip -r -X "../${LAMBDA_NAME}.zip" .
    cd ..
    rm -rf package

    echo "Done, ${current}/${LAMBDA_NAME}.zip ready to upload."
}

tf-genupload
