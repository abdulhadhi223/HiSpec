
#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parent.parent


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing configuration: {name}")
    return value


def main() -> None:
    host = required("NEC_DB_HOST")
    port = int(required("NEC_DB_PORT"))
    name = required("NEC_DB_NAME")
    user = required("NEC_APP_USER")
    password = required("NEC_APP_PASS")

    if name != "nmdb_nec":
        raise RuntimeError(
            "NEC migrations must target nmdb_nec"
        )

    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid NEC_DB_PORT")

    ini_file = ROOT / "alembic.nec.ini"
    env_file = ROOT / "alembic_nec" / "env.py"
    versions = ROOT / "alembic_nec" / "versions"

    for path in (ini_file, env_file, versions):
        if not path.exists():
            raise RuntimeError(
                f"Missing migration path: {path}"
            )

    url = URL.create(
        drivername="postgresql+psycopg2",
        username=user,
        password=password,
        host=host,
        port=port,
        database=name,
    ).render_as_string(hide_password=False)

    env = os.environ.copy()

    # Both application and Alembic use the NEC DB.
    env["DATABASE_URL"] = url
    env["NEC_MIGRATION_DATABASE_URL"] = url
    env["NEC_SCHEMA"] = "public"
    env["APP_MODE"] = "nec"

    # Prevent SQLAlchemy from writing to another schema.
    env["PGOPTIONS"] = "-c search_path=public"

    if "--check" in sys.argv:
        print("NEC migration configuration validated")
        print(f"Database: {name}")
        print("Schema: public")
        return

    print("Starting NEC Alembic migration", flush=True)
    print(f"Database: {name}", flush=True)
    print("Schema: public", flush=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ini_file),
            "upgrade",
            "head",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )

    print("NEC Alembic migration completed")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(
            f"NEC migration failed: exit code "
            f"{exc.returncode}",
            file=sys.stderr,
        )
        sys.exit(exc.returncode)



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
set -euo pipefail
set +x

: "${NEC_DB_HOST:?Missing NEC_DB_HOST}"
: "${NEC_DB_PORT:?Missing NEC_DB_PORT}"
: "${NEC_DB_NAME:?Missing NEC_DB_NAME}"

test -x .venv/bin/python

# Check configuration and migration files.
.venv/bin/python scripts/run_nec_migrations.py --check

# Run migrations against nmdb_nec.public.
.venv/bin/python scripts/run_nec_migrations.py

echo "NEC migration stage completed"
'''
        }
    }
}
