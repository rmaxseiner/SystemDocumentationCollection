pipeline {
    agent {
        label 'docker'
    }

    environment {
        REGISTRY = 'registry.maxseiner.casa'
        IMAGE_NAME = 'infrastructure-docs-collector'
        IMAGE_TAG = "${env.BUILD_NUMBER}"
        DEPLOY_PATH = '/opt/infrastructure-docs-collector'
    }

    triggers {
        // Run daily at 2 AM
        cron('0 2 * * *')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build') {
            steps {
                script {
                    echo "Building Docker image: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
                    sh "docker build -t ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} ."
                    sh "docker tag ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${IMAGE_NAME}:latest"
                }
            }
        }

        stage('Push') {
            steps {
                script {
                    echo "Pushing to registry: ${REGISTRY}"
                    withCredentials([usernamePassword(credentialsId: 'docker-registry', usernameVariable: 'REGISTRY_USER', passwordVariable: 'REGISTRY_PASS')]) {
                        sh "echo \$REGISTRY_PASS | docker login ${REGISTRY} -u \$REGISTRY_USER --password-stdin"
                        sh "docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
                        sh "docker push ${REGISTRY}/${IMAGE_NAME}:latest"
                    }
                }
            }
        }

        stage('Deploy') {
            steps {
                script {
                    echo "Deploying infrastructure documentation collector"

                    // Create deployment directory if it doesn't exist
                    sh "mkdir -p ${DEPLOY_PATH}"

                    // Copy docker-compose file to deployment directory
                    sh "cp docker-compose.yml ${DEPLOY_PATH}/"
                    sh "cp .env.example ${DEPLOY_PATH}/.env || true"

                    // Pull latest image and restart container
                    sh """
                        cd ${DEPLOY_PATH}
                        docker-compose pull
                        docker-compose up -d
                    """
                }
            }
        }

        stage('Verify') {
            steps {
                script {
                    echo "Verifying deployment"
                    sh """
                        cd ${DEPLOY_PATH}
                        docker-compose ps
                        docker-compose logs --tail=50
                    """
                }
            }
        }
    }

    post {
        success {
            echo "Pipeline completed successfully!"
            echo "Infrastructure documentation collection scheduled to run daily at 2 AM"
        }
        failure {
            echo "Pipeline failed. Check logs for details."
        }
        always {
            // Cleanup dangling images
            sh "docker image prune -f || true"
        }
    }
}
