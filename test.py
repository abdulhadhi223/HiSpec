
stage('Migrate NEC Database') {
    when {
        expression {
            return params.IMAGE_TAG?.trim() &&
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
set +x
set -euo pipefail

: "${NEC_DB_HOST:?}"
: "${NEC_DB_PORT:?}"
: "${NEC_DB_NAME:?}"

# Ensure NEC database migration files exist.
test -f alembic.nec.ini
test -f alembic_nec/env.py
test -d alembic_nec/versions

# Reuse the Jenkins offline Python environment.
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
    . .venv/bin/activate
    pip install --quiet --no-index --find-links=wheels \
        -r requirements.txt
    pip install --quiet --no-index --find-links=wheels \
        psycopg2-binary
else
    . .venv/bin/activate
fi

# The NEC env.py must read this variable.
export NEC_MIGRATION_DATABASE_URL="$(
python - <<'PY'
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
PY
)"

# Keep environment-variable names consistent
# with the NEC Alembic env.py.
export DATABASE_URL="$NEC_MIGRATION_DATABASE_URL"

echo "Running NEC migrations on ${NEC_DB_NAME}.public"

alembic -c alembic.nec.ini upgrade head

echo "NEC Alembic migration completed"
'''
        }
    }
}
