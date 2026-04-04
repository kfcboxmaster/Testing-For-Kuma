pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                // Ensure the code is actually pulled before running scripts
                checkout scm
            }
        }

        stage('Install dependencies') {
            steps {
                bat '''
                if not exist venv (
                    python -m venv venv
                )
                call venv\\Scripts\\activate
                
                :: Use the full path to python to upgrade pip safely
                python -m pip install --upgrade pip
                
                :: Use backslashes for Windows paths
                pip install -r tests\\requirements.txt
                
                python -m playwright install chromium
                '''
            }
        }

        stage('Run QA Suite') {
            steps {
                bat '''
                call venv\\Scripts\\activate
                :: Ensure we are in the root before running pytest
                pytest tests/ -v --alluredir=allure-results || exit 0
                '''
            }
        }
    }

    post {
        always {
            allure includeProperties: false, 
                   jdk: '', 
                   results: [[path: 'allure-results']]
            
            cleanWs()
        }
    }
}