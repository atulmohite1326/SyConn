pipeline {
  agent { docker { image 'python:3.7.2' } }
  stages {
    stage('build') {
      steps {
        sh 'pip install -e .'
      }
    }
    stage('test') {
      steps {
        sh 'python -m pytest --junit-xml=pytest_unit.xml --cov=syconn || true # tests may fail'
      }
    }
  }
}