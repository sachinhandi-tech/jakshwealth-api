#!/bin/bash
# creating zip and pushing it to s3 bucket
set -e
echo "Script started"

AWS_PROFILE="${AWS_PROFILE:-jakshwealth}"
export AWS_PROFILE
aws sts get-caller-identity

function_list="$WORKSPACE/automation_codes/text_files/py_function_list.txt"

s3_bucket="jakshwealth-artifacts-$1"
s3_key="jw-api/"

lambda_source_hash() {
    local lambda_dir="$1"
    (
        cd "$lambda_dir"
        find ./ -type f \
            ! -path './tests/*' \
            ! -path './tf-virtual-env/*' \
            ! -path './package/*' \
            ! -path './__pycache__/*' \
            ! -path './.pytest_cache/*' \
            ! -name '*.zip' \
            -print0 | sort -z | xargs -0 sha256sum
        find ./ \( -type f -o -type d \) \
            ! -path './tests/*' \
            ! -path './tf-virtual-env/*' \
            ! -path './package/*' \
            ! -path './__pycache__/*' \
            ! -path './.pytest_cache/*' \
            ! -name '*.zip' \
            -print0 | sort -z | xargs -0 stat -c '%n'
        sha256sum "${WORKSPACE}/.cicd/lambda_package.sh"
    ) | sha256sum | awk '{print $1}'
}

verify_lambda_zip() {
    local zip_file="$1"
    local function_name="$2"

    if [ "$function_name" = "jw_secure_data" ]; then
        if ! unzip -l "$zip_file" | grep -q 'features/__init__.py'; then
            echo "ERROR: ${zip_file} is missing features/__init__.py"
            exit 1
        fi
    fi
}

while IFS= read -r line
do
    function_name="$line"
    echo "$function_name"
    lambda_dir="${WORKSPACE}/lambda/${function_name}"
    zip_file="${lambda_dir}/${function_name}.zip"

    LOCAL_DIR_HASH="$(lambda_source_hash "$lambda_dir")"
    echo "Local directories hash is ${LOCAL_DIR_HASH}"

    LAST_DIR_HASH="$(
        aws s3api head-object \
            --bucket "${s3_bucket}" \
            --key "${s3_key}${function_name}.zip" \
            | jq --raw-output '.Metadata.dir_hash // empty' \
            | awk '{print $1}'
    )"
    echo "Cloud hash from past is ${LAST_DIR_HASH}"

    if [[ "$LOCAL_DIR_HASH" != "$LAST_DIR_HASH" ]]; then
        chmod +x "${WORKSPACE}/.cicd/lambda_package.sh"
        "${WORKSPACE}/.cicd/lambda_package.sh" "$lambda_dir"
        verify_lambda_zip "$zip_file" "$function_name"
        aws s3 cp "$zip_file" "s3://${s3_bucket}/${s3_key}" \
            --metadata "dir_hash=${LOCAL_DIR_HASH}"
        echo "$function_name pushed to s3 bucket!"
    else
        echo "$function_name - No change from the last time. So, skipping it!"
    fi
done < "$function_list"

echo "Script ran successfully"
# file name and location: .cicd directory and 'python_lambda_s3_push.sh'
