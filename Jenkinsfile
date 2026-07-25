#!/usr/bin/groovy

def props

def jakshAws(Closure body) {
    withCredentials([[
        $class: 'AmazonWebServicesCredentialsBinding',
        credentialsId: 'jakshwealth-aws',
        accessKeyVariable: 'AWS_ACCESS_KEY_ID',
        secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
    ]]) {
        withEnv([
            "AWS_DEFAULT_REGION=${env.AWS_REGION}",
            "AWS_REGION=${env.AWS_REGION}",
            'AWS_PROFILE=jakshwealth'
        ]) {
            sh '''
                mkdir -p "${HOME}/.aws"
                cat > "${HOME}/.aws/credentials" <<EOF
[jakshwealth]
aws_access_key_id=${AWS_ACCESS_KEY_ID}
aws_secret_access_key=${AWS_SECRET_ACCESS_KEY}
EOF
            '''
            body()
        }
    }
}

pipeline {
    agent any

    parameters {
        choice(
            name: 'TERRAFORM_ACTION',
            choices: ['apply', 'destroy'],
            description: 'apply = deploy Lambdas + API integrations; destroy = tear down (gw_deploy first, then main).'
        )
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timestamps()
        disableConcurrentBuilds()
    }

    stages {
        stage('Set environment') {
            steps {
                script {
                    if (env.BRANCH_NAME == 'main' || env.BRANCH_NAME == 'master') {
                        props = readProperties file: "${WORKSPACE}/.cicd/build_props/prod-build.properties"
                    } else if (env.BRANCH_NAME == 'test') {
                        props = readProperties file: "${WORKSPACE}/.cicd/build_props/test-build.properties"
                    } else {
                        props = readProperties file: "${WORKSPACE}/.cicd/build_props/dev-build.properties"
                    }
                    env.AWS_CREDENTIALS_ID = props.aws_credentials_id ?: 'jakshwealth-aws'
                    env.AWS_REGION = props.aws_region ?: 'us-east-1'
                    env.DEPLOY_ENV = props.deploy_env
                }
            }
        }

        stage('Verify AWS credentials') {
            steps {
                script {
                    jakshAws {
                        sh 'aws sts get-caller-identity'
                    }
                }
            }
        }

        stage('Generate Terraform') {
            steps {
                sh '''
                    cd automation_codes/python_scripts
                    python3 generate_tf.py --env "${DEPLOY_ENV}" --rest_api jw-api
                '''
            }
        }

        stage('Push Lambda artifacts to S3') {
            when {
                expression { params.TERRAFORM_ACTION == 'apply' }
            }
            steps {
                script {
                    jakshAws {
                        sh '''
                            chmod +x .cicd/*.sh
                            .cicd/python_lambda_s3_push.sh "${DEPLOY_ENV}"
                        '''
                    }
                }
            }
        }

        stage('Terraform') {
            steps {
                script {
                    jakshAws {
                        sh '''
                            export TF_ACTION="${TERRAFORM_ACTION}"

                            rm -rf jakshwealth-infra
                            git clone --branch main --single-branch --depth 1 \
                              https://github.com/sachinhandi-tech/jakshwealth-infra.git jakshwealth-infra

                            run_terraform() {
                              local tf_dir="$1"
                              local stack_name="$2"
                              echo "terraform ${TF_ACTION} — ${stack_name}"
                              cd "${tf_dir}"
                              terraform init -backend-config="backend.${DEPLOY_ENV}.tfvars"
                              if [ "${TF_ACTION}" = "destroy" ]; then
                                terraform plan -destroy -var-file="vars.${DEPLOY_ENV}.tfvars" -out=tfplan.out
                              else
                                terraform plan -var-file="vars.${DEPLOY_ENV}.tfvars" -out=tfplan.out
                              fi
                              terraform apply -auto-approve tfplan.out
                            }

                            MAIN_TF_DIR="${WORKSPACE}/automation_codes/terraforms"
                            GW_TF_DIR="${WORKSPACE}/automation_codes/terraforms/gw_deploy"

                            if [ "${TF_ACTION}" = "destroy" ]; then
                              run_terraform "${GW_TF_DIR}" gw_deploy
                              run_terraform "${MAIN_TF_DIR}" main
                            else
                              run_terraform "${MAIN_TF_DIR}" main
                              run_terraform "${GW_TF_DIR}" gw_deploy
                            fi
                        '''
                    }
                }
            }
        }

        stage('Deploy API Gateway stage') {
            when {
                expression { params.TERRAFORM_ACTION == 'apply' }
            }
            steps {
                script {
                    jakshAws {
                        sh '''
                            API_ID=$(aws apigateway get-rest-apis \
                              --query "items[?name=='jw-api'].id | [0]" --output text)
                            aws apigateway create-deployment \
                              --rest-api-id "${API_ID}" \
                              --stage-name "${DEPLOY_ENV}" \
                              --description "Jenkins deploy ${BUILD_NUMBER} on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
                        '''
                    }
                }
            }
        }
    }
}
