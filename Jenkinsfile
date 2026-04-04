pipeline {
    agent any

    environment {
        // Force python to not buffer output so you see logs in real-time
        PYTHONUNBUFFERED = '1'
    }

    stages {
        stage('Install dependencies') {
            steps {
                sh '''
                python3 -m venv venv
                . venv/bin/activate
                pip install --upgrade pip
                pip install -r tests/requirements.txt
                python -m playwright install chromium
                '''
            }
        }

        stage('Run QA Suite') {
            steps {
                sh '''
                . venv/bin/activate
                # Run all tests and generate allure results
                pytest tests/ -v || true
                '''
            }
        }
    }

    post {
        always {
            // Generate the Allure report even if tests failed
            allure includeProperties: false, 
                   jdk: '', 
                   results: [[path: 'allure-results']]
            
            // Clean up the workspace to save disk space
            cleanWs()
        }
    }
}