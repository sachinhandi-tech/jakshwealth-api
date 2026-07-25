#!/usr/bin/groovy
def props
def BuildCause = currentBuild.getBuildCauses().get(0)

pipeline {
    agent {
        kubernetes {
            cloud "jakshwealth-ccd-openshift-devops1"
            inheritFrom "ccd-api-pod"
            customWorkspace "/home/jenkins/agent/workspace"
            defaultContainer "cloudkit"
            yamlFile ".cicd/build-agent.yaml"
        }
    }

    parameters {
        choice(
            name: 'TERRAFORM_ACTION',
            choices: ['apply', 'destroy'],
            description: 'Terraform action: apply deploys infrastructure; destroy tears it down (gw_deploy first, then main stack).'
        )
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        ansiColor('xterm')
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        ROLE_NAME                = "HPNCCDJENKINS"
        WEBEX_HOOK               = "https://webexapis.com/v1/webhooks/incoming/Y2lzY29zcGFyazovL3VzL1dFQkhPT0svN2Y5ZTU4NGQtZDBmYi00ZjFhLTg1MDQtM2FmZDNiZGU3NzA4"
        TEAMS_WEBHOOK            = "https://default791b26cb3fdf47c3b85dbd9f037e3e.7f.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/51f1e70673f94ef0ae2f12ff53b6a209/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=mhcu-uFVL2CZL6QquNxtuzwpvqaR28r53NQNi88fRIA"
        RELEASE_AUTOMATION_LAMBDA = "ccd_release_automation"
    }

    stages {

        // -------------------------------------------------------
        // Stage 1: Set Environment
        // -------------------------------------------------------
        stage('Set Environment') {
            steps {
                script {
                    if (env.BRANCH_NAME == 'dev') {
                        props = readProperties file: "${WORKSPACE}/.cicd/build_props/dev-build.properties"
                    } else {
                        error("Pipeline only supports the dev branch (current: ${env.BRANCH_NAME})")
                    }
                    env.AWS_PROFILE        = props.aws_profile ?: 'jakshwealth'
                    env.AWS_ACCOUNT_NUMBER = props.account_number
                    env.AWS_REGION         = props.aws_region ?: 'us-east-1'
                    env.DEPLOY_ENV         = props.deploy_env
                }
            }
        }

        // -------------------------------------------------------
        // Stage 3: Verify AWS credentials (personal IAM profile)
        // -------------------------------------------------------
        stage('Verify AWS credentials') {
            steps {
                sh """
                    export AWS_PROFILE=${AWS_PROFILE}
                    export AWS_DEFAULT_REGION=${AWS_REGION}
                    aws sts get-caller-identity
                    mkdir -p ${WORKSPACE}/.cicd
                    cp ~/.aws/credentials ${WORKSPACE}/.cicd/credentials 2>/dev/null || true
                """
            }
        }

        // -------------------------------------------------------
        // Stage 4: Open Release Ticket
        // -------------------------------------------------------
        stage('Open Release Ticket') {
            when {
                expression { params.TERRAFORM_ACTION == 'apply' }
            }
            steps {
                script {
                    if (env.BRANCH_NAME != 'test') {
                        withCredentials([string(credentialsId: 'servicenow-creds', variable: 'servicenow_creds')]) {
                            sh '''
                                export AWS_PROFILE=${AWS_PROFILE}
                                export AWS_DEFAULT_REGION=${AWS_REGION}
                                export PLAN_START=$(date -u -d "+1 hour" "+%Y-%m-%d %H:%M:%S")
                                export PLAN_END=$(date -u -d "+3 hours" "+%Y-%m-%d %H:%M:%S")

                                cat > payload.json << EOF
{
    "httpMethod": "POST",
    "headers": {
        "Authorization": "${servicenow_creds}"
    },
    "pathParameters": {
        "func_name": "start-release"
    },
    "body": "{\\"releaseManager\\": \\"Fleitz, Frederick\\", \\"planStart\\": \\"${PLAN_START}\\", \\"planEnd\\": \\"${PLAN_END}\\"}"
}
EOF

                                aws lambda invoke \
                                    --cli-binary-format raw-in-base64-out \
                                    --function-name ${RELEASE_AUTOMATION_LAMBDA}_${DEPLOY_ENV} \
                                    --payload file://payload.json \
                                    output.json
                            '''
                        }
                    }
                }
            }
        }
        stage ('Generate scripts') {
            steps {
                container('python-312-ubi9') {
                    sh "echo 'Run the python script to autogenerate the terraform scripts'"
                    sh """
                        cd ${WORKSPACE}/automation_codes/python_scripts
                        python -V
                        python generate_tf.py --env ${DEPLOY_ENV} --rest_api jw-api
                    """
                }
            }
        }

        // -------------------------------------------------------
        // Stage 7: Code Push to S3
        // -------------------------------------------------------
        stage('Code Push to S3') {
            when {
                expression { params.TERRAFORM_ACTION == 'apply' }
            }
            steps {
                container('python-312-ubi9') {
                    sh "echo 'Pushing lambda zip artifacts to s3 bucket'"
                    sh """
                        export AWS_PROFILE=${AWS_PROFILE}
                        export AWS_DEFAULT_REGION=${AWS_REGION}
                        aws sts get-caller-identity

                        chmod +x ${WORKSPACE}/.cicd/*.sh
                        ${WORKSPACE}/.cicd/python_lambda_s3_push.sh ${DEPLOY_ENV}
                    """
                }
            }
        }

        // -------------------------------------------------------
        // Stage 8: Generate and Run Terraforms
        // -------------------------------------------------------
        stage('Generate and Run Terraforms') {
            steps {
                sh "echo 'Terraform action: ${params.TERRAFORM_ACTION}'"
                sh """
                    export AWS_PROFILE=${AWS_PROFILE}
                    export AWS_DEFAULT_REGION=${AWS_REGION}
                    export TF_ACTION="${params.TERRAFORM_ACTION}"
                    aws sts get-caller-identity

                    # Clone jakshwealth-infra once for local module references
                    cd ${WORKSPACE}
                    if [ "${DEPLOY_ENV}" = "dev" ]; then
                        INFRA_BRANCH="develop"
                    elif [ "${DEPLOY_ENV}" = "prod" ]; then
                        INFRA_BRANCH="master"
                    else
                        INFRA_BRANCH="${DEPLOY_ENV}"
                    fi
                    git clone --branch \${INFRA_BRANCH} --single-branch --depth 1 https://github.sys.cigna.com/cigna/jakshwealth-infra.git jakshwealth-infra

                    run_terraform() {
                        local tf_dir="\$1"
                        local stack_name="\$2"
                        echo "Running terraform \${TF_ACTION} for \${stack_name} in \${tf_dir}"
                        cd "\${tf_dir}"
                        tfswitch 1.1.9
                        terraform -version
                        terraform init -backend-config=backend.${DEPLOY_ENV}.tfvars -backend=true
                        terraform refresh -var-file=vars.${DEPLOY_ENV}.tfvars
                        if [ "\${TF_ACTION}" = "destroy" ]; then
                            terraform plan -destroy -var-file=vars.${DEPLOY_ENV}.tfvars -out=./tfplan.out
                        else
                            terraform plan -var-file=vars.${DEPLOY_ENV}.tfvars -out=./tfplan.out
                        fi
                        terraform apply -auto-approve ./tfplan.out
                    }

                    MAIN_TF_DIR="${WORKSPACE}/automation_codes/terraforms"
                    GW_TF_DIR="${WORKSPACE}/automation_codes/terraforms/gw_deploy"

                    if [ "\${TF_ACTION}" = "destroy" ]; then
                        # Reverse dependency order: stage/logging/domain before lambdas and integrations
                        run_terraform "\${GW_TF_DIR}" "gw_deploy"
                        run_terraform "\${MAIN_TF_DIR}" "main"
                    else
                        run_terraform "\${MAIN_TF_DIR}" "main"
                        run_terraform "\${GW_TF_DIR}" "gw_deploy"
                    fi
                """
            }
        }

        // -------------------------------------------------------
        // Stage 9: Deploy the API Gateway
        // -------------------------------------------------------
        stage('Deploy the API Gateway') {
            when {
                expression { params.TERRAFORM_ACTION == 'apply' }
            }
            steps {
                sh "echo 'Deploy the api gateway without TF'"
                sh '''
                    export AWS_PROFILE=${AWS_PROFILE}
                    export AWS_DEFAULT_REGION=${AWS_REGION}
                    aws sts get-caller-identity

                    export DEPLOY_DATE=$(date)
                    export apiId=$(aws apigateway get-rest-apis | jq -r '.items[] | select(.name == "jw-api") | .id')

                    aws apigateway create-deployment \
                        --rest-api-id ${apiId} \
                        --stage-name ${DEPLOY_ENV} \
                        --description "Deployment for ${DEPLOY_ENV} on ${DEPLOY_DATE}"
                '''
            }
        }
    }

    // ===========================================================
    // Post Actions
    // ===========================================================
    post {

        failure {
            echo "### Gathering Failure Information"

            // Webex notification
            sh """
                curl -X POST -H "Content-Type: application/json" \
                    -d '{"markdown": "Build INFO jakshwealth-api: ${JOB_BASE_NAME} <br> Branch: ${BRANCH_NAME} <br> Build Number: ${BUILD_NUMBER} <br> Environment: ${DEPLOY_ENV} <br> JakshWealth API: Build ${currentBuild.result} <br> Build Log: ${BUILD_URL}"}' \
                    ${WEBEX_HOOK}
            """

            // MS Teams notification (Adaptive Card)
            sh '''
                cat > /tmp/teams_payload.json << EOFTEAMS
{
    "type": "message",
    "attachments": [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": null,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "size": "Large",
                        "weight": "Bolder",
                        "color": "Attention",
                        "text": "❌ JakshWealth API Build FAILED"
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            { "title": "Job:", "value": "REPLACE_JOB" },
                            { "title": "Branch:", "value": "REPLACE_BRANCH" },
                            { "title": "Build #:", "value": "REPLACE_BUILD_NUM" },
                            { "title": "Environment:", "value": "REPLACE_ENV" }
                        ]
                    },
                    {
                        "type": "ActionSet",
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View Build Log",
                                "url": "REPLACE_URL"
                            }
                        ]
                    }
                ]
            }
        }
    ]
}
EOFTEAMS
                sed -i "s|REPLACE_JOB|${JOB_BASE_NAME}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_BRANCH|${BRANCH_NAME}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_BUILD_NUM|${BUILD_NUMBER}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_ENV|${DEPLOY_ENV}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_URL|${BUILD_URL}|g" /tmp/teams_payload.json
                curl -X POST -H "Content-Type: application/json" \
                    -d @/tmp/teams_payload.json \
                    "${TEAMS_WEBHOOK}"
            '''
        }

        success {
            echo "### Reporting Success"

            // Webex notification
            sh """
                curl -X POST -H 'Content-type: application/json' \
                    -d '{"markdown": "Build INFO jakshwealth-api: ${JOB_BASE_NAME} <br> Branch: ${BRANCH_NAME} <br> Build Number: ${BUILD_NUMBER} <br> Environment: ${DEPLOY_ENV} <br> JakshWealth API: Build ${currentBuild.result} <br> Build Log: ${BUILD_URL}"}' \
                    ${WEBEX_HOOK}
            """

            // MS Teams notification (Adaptive Card)
            sh '''
                cat > /tmp/teams_payload.json << EOFTEAMS
{
    "type": "message",
    "attachments": [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": null,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "size": "Large",
                        "weight": "Bolder",
                        "color": "Good",
                        "text": "✅ JakshWealth API Build SUCCESS"
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            { "title": "Job:", "value": "REPLACE_JOB" },
                            { "title": "Branch:", "value": "REPLACE_BRANCH" },
                            { "title": "Build #:", "value": "REPLACE_BUILD_NUM" },
                            { "title": "Environment:", "value": "REPLACE_ENV" }
                        ]
                    },
                    {
                        "type": "ActionSet",
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View Build Log",
                                "url": "REPLACE_URL"
                            }
                        ]
                    }
                ]
            }
        }
    ]
}
EOFTEAMS
                sed -i "s|REPLACE_JOB|${JOB_BASE_NAME}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_BRANCH|${BRANCH_NAME}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_BUILD_NUM|${BUILD_NUMBER}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_ENV|${DEPLOY_ENV}|g" /tmp/teams_payload.json
                sed -i "s|REPLACE_URL|${BUILD_URL}|g" /tmp/teams_payload.json
                curl -X POST -H "Content-Type: application/json" \
                    -d @/tmp/teams_payload.json \
                    "${TEAMS_WEBHOOK}"
            '''
        }

        always {
            script {
                if (env.BRANCH_NAME != 'test' && params.TERRAFORM_ACTION == 'apply') {
                    withCredentials([string(credentialsId: 'servicenow-creds', variable: 'servicenow_creds')]) {
                        sh '''
                            export AWS_PROFILE=${AWS_PROFILE}
                            export AWS_DEFAULT_REGION=${AWS_REGION}

                            echo "Debug: Contents of output.json:"
                            cat output.json 2>/dev/null || echo "output.json not found"

                            # Try to extract sys_id from different possible response structures
                            # The lambda returns API Gateway format with body as JSON string
                            SYS_ID=$(cat output.json 2>/dev/null | jq -r '.body | fromjson | .sys_id // empty' 2>/dev/null || echo "")

                            if [ ! -z "$SYS_ID" ] && [ "$SYS_ID" != "null" ]; then
                                echo "Closing release ticket with sys_id: $SYS_ID"

                                cat > close-payload.json << EOF
{
    "httpMethod": "POST",
    "headers": {
        "Authorization": "${servicenow_creds}"
    },
    "pathParameters": {
        "func_name": "close-release"
    },
    "body": "{\\"sys_id\\": \\"${SYS_ID}\\"}"
}
EOF

                                aws lambda invoke \
                                    --cli-binary-format raw-in-base64-out \
                                    --function-name ${RELEASE_AUTOMATION_LAMBDA}_${DEPLOY_ENV} \
                                    --payload file://close-payload.json \
                                    output-close.json

                                echo "Close operation completed. Response:"
                                cat output-close.json 2>/dev/null || echo "output-close.json not found"
                            else
                                echo "No sys_id found in output.json, skipping close operation"
                            fi
                        '''
                    }
                }
            }
        }
    }
}
