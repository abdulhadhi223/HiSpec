post {
    always {
        catchError(
            buildResult: 'SUCCESS',
            stageResult: 'UNSTABLE',
            catchInterruptions: false
        ) {
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
                sh '''#!/usr/bin/env bash
set +x
set -euo pipefail

if [[ -n "${TEST_SCHEMA:-}" && -x .venv/bin/python ]]; then

    # Only clean up this build's test schemas.
    # Reserve four characters for the NEC "_nec" suffix.
    if [[ ! "$TEST_SCHEMA" =~ ^test_[a-z0-9_]+_[0-9]+$ ]] || (( ${#TEST_SCHEMA} > 59 )); then
        echo "ERROR: Refusing cleanup of an invalid test schema"
        exit 1
    fi

    : "${NEC_TEST_DB:?NEC_TEST_DB is required}"

    export DB_APP_USER="$NMDB_APP_USER"

    rc=0

    # NMDB: remove the test schema from the existing NMDB database.
    .venv/bin/python "$SCHEMA_PY" "$TEST_SCHEMA" --drop-only --yes || rc=1

    # NEC: remove the test schema from the permanent NEC test database.
    # DB_NAME is overridden only for this command.
    DB_NAME="$NEC_TEST_DB" .venv/bin/python "$SCHEMA_PY" "${TEST_SCHEMA}_nec" --drop-only --yes || rc=1

    exit "$rc"

else
    echo "Skipping test-schema cleanup: TEST_SCHEMA or .venv/bin/python is unavailable."
fi
'''
            }
        }
    }
}