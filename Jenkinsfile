#!/usr/bin/groovy

def props

def jakshAws(Closure body) {
    def credId = env.AWS_CREDENTIALS_ID?.trim()
    def profile = env.AWS_PROFILE ?: 'jakshwealth'
    def awsEnv = [
        "AWS_DEFAULT_REGION=${env.AWS_REGION}",
        "AWS_REGION=${env.AWS_REGION}",
        "AWS_PROFILE=${profile}"
    ]

    if (credId) {
        withCredentials([[
            $class: 'AmazonWebServicesCredentialsBinding',
            credentialsId: credId,
            accessKeyVariable: 'AWS_ACCESS_KEY_ID',
            secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
        ]]) {
            withEnv(awsEnv) {
                sh """
                    mkdir -p "\${HOME}/.aws"
                    cat > "\${HOME}/.aws/credentials" <<EOF
[${profile}]
aws_access_key_id=\${AWS_ACCESS_KEY_ID}
aws_secret_access_key=\${AWS_SECRET_ACCESS_KEY}
EOF
                """
                body()
            }
        }
    } else {
        withEnv(awsEnv) {
            body()
        }
    }
}

pipeline {
    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timestamps()
        disableConcurrentBuilds()
    }

    stages {
        stage('Set environment') {
            steps {
                script {
                    props = readProperties file: "${WORKSPACE}/.cicd/build_props/build.properties"
                    env.AWS_CREDENTIALS_ID = (props.aws_credentials_id ?: '').trim()
                    env.AWS_PROFILE = props.aws_profile ?: 'jakshwealth'
                    env.AWS_REGION = props.aws_region ?: 'ap-south-2'
                    env.DEPLOY_ENV = props.deploy_env ?: 'dev'
                    env.EC2_INSTANCE_ID = props.ec2_instance_id ?: 'i-05f19a7ffb523f876'
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

        stage('Publish EC2 API bundle') {
            steps {
                script {
                    jakshAws {
                        sh '''
                            chmod +x .cicd/ec2_api_bundle.sh
                            .cicd/ec2_api_bundle.sh "${DEPLOY_ENV}"
                        '''
                    }
                }
            }
        }

        stage('Sync and install on EC2') {
            steps {
                script {
                    jakshAws {
                        sh '''
                            aws ssm send-command \
                                --instance-ids "${EC2_INSTANCE_ID}" \
                                --document-name "AWS-RunShellScript" \
                                --parameters 'commands=["sudo /usr/local/bin/kite-algo-setup-sync"]' \
                                --region "${AWS_REGION}"
                        '''
                    }
                }
            }
        }
    }
}
