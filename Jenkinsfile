pipeline {
    agent { label 'newsc-agent-1' }

    environment {
        HARBOR_HOST    = '10.192.26.160:80'
        HARBOR_PROJECT = 'newsc'
        APP_NAME       = 'nmdb-app'
        IMAGE_TAG      = "${BUILD_NUMBER}"
        IMAGE          = "${HARBOR_HOST}/${HARBOR_PROJECT}/${APP_NAME}:${IMAGE_TAG}"

        // Shared PostgreSQL host (CI instance)
        DB_HOST        = '10.192.26.4'
        DB_PORT        = '5432'
        DB_NAME        = 'nmdb_dev'
    }

    stages {

        // ----------------------------------------------------------------
        // Checkout
        // ----------------------------------------------------------------
        stage('Checkout') {
            steps {
                sh '''
                    set -e
                    echo "Jenkins multibranch env:"
                    echo "BRANCH_NAME=${BRANCH_NAME}"
                    echo "GIT_BRANCH=${GIT_BRANCH}"
                    echo "Checked out branch:"
                    git rev-parse --abbrev-ref HEAD
                    echo "Commit:"
                    git rev-parse HEAD
                '''
            }
        }

        // ----------------------------------------------------------------
        // Derive branch slug (same logic as release pipeline)
        // ----------------------------------------------------------------
        stage('Resolve Branch Slug') {
            steps {
                script {
                    def slug = (env.BRANCH_NAME ?: sh(
                        returnStdout: true,
                        script: 'git rev-parse --abbrev-ref HEAD'
                    ).trim())
                    .replaceAll('^origin/', '')
                    .replaceAll('[^a-zA-Z0-9-]', '-')
                    .toLowerCase()

                    env.BRANCH_SLUG   = slug
                    env.TEST_SCHEMA   = "test_${slug}"
                    env.TEST_DB_URL   = "postgresql://\${NMDB_APP_USER}:\${NMDB_APP_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=-csearch_path=${env.TEST_SCHEMA}"
                    echo "BRANCH_SLUG=${env.BRANCH_SLUG}"
                    echo "TEST_SCHEMA=${env.TEST_SCHEMA}"
                }
            }
        }

        // ----------------------------------------------------------------
        // Verify wheels present
        // ----------------------------------------------------------------
        stage('Verify wheels present') {
            steps {
                sh '''
                    set -e
                    test -f requirements.txt
                    test -d wheels
                    echo "Wheels count:"
                    ls -1 wheels | wc -l
                '''
            }
        }

        // ----------------------------------------------------------------
        // Setup venv
        // ----------------------------------------------------------------
        stage('Setup Python env') {
            steps {
                sh '''
                    set -e
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --quiet --no-index --find-links=wheels -r requirements.txt
                '''
            }
        }

        // ----------------------------------------------------------------
        // Provision test schema  (fresh every build)
        // ----------------------------------------------------------------
        stage('Provision Test Schema') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'nmdb-db-admin',
                        usernameVariable: 'DB_ADMIN_USER',
                        passwordVariable: 'DB_ADMIN_PASS'
                    ),
                    usernamePassword(
                        credentialsId: 'nmdb-db-app',
                        usernameVariable: 'NMDB_APP_USER',
                        passwordVariable: 'NMDB_APP_PASS'
                    )
                ]) {
                    sh '''
                        set -euo pipefail
                        . .venv/bin/activate

                        export DB_ADMIN_URL="postgresql://${DB_ADMIN_USER}:${DB_ADMIN_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
                        export DB_APP_USER="${NMDB_APP_USER}"

                        # Drop and recreate for clean slate every build
                        python provision_schema.py "${TEST_SCHEMA}" --drop-first

                        echo "Test schema ready: ${TEST_SCHEMA}"
                    '''
                }
            }
        }

        // ----------------------------------------------------------------
        // Run Alembic migrations on test schema
        // ----------------------------------------------------------------
        stage('Migrate Test Schema') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'nmdb-db-app',
                        usernameVariable: 'NMDB_APP_USER',
                        passwordVariable: 'NMDB_APP_PASS'
                    )
                ]) {
                    sh '''
                        set -euo pipefail
                        . .venv/bin/activate

                        export DATABASE_URL="postgresql://${NMDB_APP_USER}:${NMDB_APP_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=-csearch_path=${TEST_SCHEMA}"

                        alembic upgrade head

                        echo "Alembic migrations applied to ${TEST_SCHEMA}"
                    '''
                }
            }
        }

        // ----------------------------------------------------------------
        // Run pytest against test schema
        // ----------------------------------------------------------------
        stage('Run Tests') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'nmdb-db-app',
                        usernameVariable: 'NMDB_APP_USER',
                        passwordVariable: 'NMDB_APP_PASS'
                    )
                ]) {
                    sh '''
                        set -euo pipefail
                        . .venv/bin/activate

                        export DATABASE_URL="postgresql://${NMDB_APP_USER}:${NMDB_APP_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=-csearch_path=${TEST_SCHEMA}"
                        export TEST_DATABASE_URL="${DATABASE_URL}"
                        export TESTING=1

                        pytest tests/ \
                            --tb=short \
                            -q \
                            --junitxml=test-results/junit.xml \
                            --cov=app \
                            --cov-report=xml:coverage.xml
                    '''
                }
            }
            post {
                always {
                    junit 'test-results/junit.xml'
                }
                failure {
                    echo "Tests failed — image will NOT be built or pushed"
                }
            }
        }

        // ----------------------------------------------------------------
        // Drop test schema after tests (keep CI DB clean)
        // ----------------------------------------------------------------
        stage('Cleanup Test Schema') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'nmdb-db-admin',
                        usernameVariable: 'DB_ADMIN_USER',
                        passwordVariable: 'DB_ADMIN_PASS'
                    ),
                    usernamePassword(
                        credentialsId: 'nmdb-db-app',
                        usernameVariable: 'NMDB_APP_USER',
                        passwordVariable: 'NMDB_APP_PASS'
                    )
                ]) {
                    sh '''
                        set -euo pipefail
                        . .venv/bin/activate

                        export DB_ADMIN_URL="postgresql://${DB_ADMIN_USER}:${DB_ADMIN_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
                        export DB_APP_USER="${NMDB_APP_USER}"

                        python provision_schema.py "${TEST_SCHEMA}" --drop-first
                        echo "Test schema dropped: ${TEST_SCHEMA}"
                    '''
                }
            }
        }

        // ----------------------------------------------------------------
        // Build Docker image
        // ----------------------------------------------------------------
        stage('Build Docker Image') {
            steps {
                sh '''
                    set -e
                    docker version
                    docker build -t ${IMAGE} .
                '''
            }
        }

        // ----------------------------------------------------------------
        // Push to Harbor
        // ----------------------------------------------------------------
        stage('Push to Harbor') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'Harbor',
                    usernameVariable: 'HUSER',
                    passwordVariable: 'HPASS'
                )]) {
                    sh '''
                        set -e
                        echo "$HPASS" | docker login "${HARBOR_HOST}" -u "$HUSER" --password-stdin
                        docker push "${IMAGE}"
                        docker logout "${HARBOR_HOST}"
                    '''
                }
            }
        }

        // ----------------------------------------------------------------
        // Trigger Release pipeline
        // ----------------------------------------------------------------
        stage('Trigger Release') {
            steps {
                script {
                    def branch = env.BRANCH_NAME
                        ?: sh(returnStdout: true,
                              script: 'git rev-parse --abbrev-ref HEAD').trim()

                    def encoded = branch.replace('/', '%2F')
                    def jobPath  = "NMDB-Release-vm/${encoded}"

                    echo "Triggering ${jobPath} with IMAGE_TAG=${env.BUILD_NUMBER}"

                    build job: jobPath,
                          wait: false,
                          parameters: [
                              string(name: 'IMAGE_TAG',      value: env.BUILD_NUMBER),
                              string(name: 'SOURCE_BRANCH',  value: branch)
                          ]
                }
            }
        }
    }
}