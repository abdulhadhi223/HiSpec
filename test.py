
stage('Migrate NEC Database') {
    when {
        expression {
            return params.IMAGE_TAG.trim() &&
                   params.DEPLOY_TARGET == 'nec'
        }
    }

    steps {
        withCredentials([
            usernamePassword(
                credentialsId: 'nec-db-app',
                usernameVariable: 'NEC_APP_USER',
                passwordVariable: 'NEC_APP_PASS'
            )
        ]) {
            sh '''#!/usr/bin/env bash
set -euo pipefail
set +x

# Validate required variables
: "${NEC_DB_HOST:?Missing NEC_DB_HOST}"
: "${NEC_DB_PORT:?Missing NEC_DB_PORT}"
: "${NEC_DB_NAME:?Missing NEC_DB_NAME}"
: "${NEC_APP_USER:?Missing NEC_APP_USER}"
: "${NEC_APP_PASS:?Missing NEC_APP_PASS}"

# Verify Alembic files
test -f alembic.nec.ini
test -f alembic_nec/env.py
test -d alembic_nec/versions

# Reuse Jenkins Python environment
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
    .venv/bin/pip install --quiet --no-index --find-links=wheels -r requirements.txt
    .venv/bin/pip install --quiet --no-index --find-links=wheels psycopg2-binary
fi

# Construct SQLAlchemy database URL safely
export DATABASE_URL="$( .venv/bin/python -c '
import os
from sqlalchemy.engine import URL

url = URL.create(
    "postgresql+psycopg2",
    username=os.environ["NEC_APP_USER"],
    password=os.environ["NEC_APP_PASS"],
    host=os.environ["NEC_DB_HOST"],
    port=int(os.environ["NEC_DB_PORT"]),
    database=os.environ["NEC_DB_NAME"]
)

print(url.render_as_string(hide_password=False))
' )"

export NEC_MIGRATION_DATABASE_URL="$DATABASE_URL"

echo "Starting NEC database migration"
echo "Database: ${NEC_DB_NAME}"
echo "Schema: public"

.venv/bin/alembic -c alembic.nec.ini upgrade head

echo "NEC Alembic migration completed successfully"
'''
        }
    }
}
