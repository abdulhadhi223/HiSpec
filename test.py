
stage('Deploy NEC to static VM') {
    when {
        expression {
            return params.IMAGE_TAG?.trim() &&
                   params.DEPLOY_TARGET == 'nec'
        }
    }

    steps {
        withCredentials([
            usernamePassword(
                credentialsId: 'Harbor',
                usernameVariable: 'HUSER',
                passwordVariable: 'HPASS'
            ),
            usernamePassword(
                credentialsId: 'nec-db-app',
                usernameVariable: 'NEC_APP_USER',
                passwordVariable: 'NEC_APP_PASS'
            )
        ]) {
            withEnv([
                "APP_HEALTH_PATH=${params.APP_HEALTH_PATH ?: '/health'}"
            ]) {
                sh '''#!/usr/bin/env bash
set +x
set -euo pipefail

# Validate configuration
: "${NEC_STATIC_VM_NAME:?Missing NEC VM name}"
: "${NEC_STATIC_VM_IP:?Missing NEC VM IP}"
: "${NEC_DB_HOST:?Missing NEC DB host}"
: "${NEC_DB_PORT:?Missing NEC DB port}"
: "${NEC_DB_NAME:?Missing NEC DB name}"
: "${FULL_IMAGE:?Missing NEC image}"
: "${NEC_APP_USER:?Missing NEC DB user}"
: "${NEC_APP_PASS:?Missing NEC DB password}"

# Build database URL with encoded credentials.
export DATABASE_URL="$(
python3 - <<'PY'
import os
from urllib.parse import quote

user = quote(os.environ["NEC_APP_USER"], safe="")
password = quote(os.environ["NEC_APP_PASS"], safe="")
host = os.environ["NEC_DB_HOST"]
port = int(os.environ["NEC_DB_PORT"])
database = quote(os.environ["NEC_DB_NAME"], safe="")

print(
    f"postgresql+asyncpg://{user}:{password}"
    f"@{host}:{port}/{database}"
)
PY
)"

# Permanent NEC database schema
export NEC_SCHEMA="public"
export APP_MODE="nec"
export APP_ENVIRONMENT="nec"

# Reuse existing release manager.
python3 "$RELEASE_PY" deploy \
    --name "$NEC_STATIC_VM_NAME" \
    --ip "$NEC_STATIC_VM_IP"

echo "NEC deployment completed"
'''
            }
        }
    }
}
