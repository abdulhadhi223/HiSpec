#!/usr/bin/env python3
"""Small shared helpers for NMDB Jenkins build/release pipelines."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys


def normalize_branch(raw: str) -> str:
    branch = (raw or "").strip()
    for prefix in ("refs/heads/", "origin/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix):]
    if not branch or branch == "HEAD":
        raise ValueError("Unable to resolve branch name")
    return branch


def slugify(branch: str, max_len: int = 44) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalize_branch(branch)).strip("_").lower()
    if not slug:
        raise ValueError("Branch produced an empty slug")
    if len(slug) > max_len:
        digest = hashlib.sha1(branch.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:max_len-9]}_{digest}"
    return slug


def is_staging_branch(branch: str) -> bool:
    b = normalize_branch(branch).lower()
    return any(b == prefix or b.startswith(prefix + "/") for prefix in ("release", "stage", "staging"))


def resolve(branch: str, build_number: str = "") -> dict:
    branch = normalize_branch(branch)
    slug = slugify(branch)
    staging = is_staging_branch(branch)
    result = {
        "branch": branch,
        "slug": slug,
        "is_staging": staging,
        "db_host": "10.192.24.81" if staging else "10.192.24.76",
        "db_port": "8080",
        "db_name": "nmdb_staging" if staging else "nmdb_dev",
        "deploy_schema": ("stage_" if staging else "dev_") + slug,
        "vm_name": "nmdb-" + slug,
    }
    if build_number:
        bn = re.sub(r"[^0-9]", "", str(build_number)) or "0"
        # Unique per build, so parallel/rerun test jobs never share the same schema.
        result["test_schema"] = f"test_{slug}_{bn}"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--branch", required=True)
    p.add_argument("--build-number", default="")
    p.add_argument("--format", choices=("json", "shell"), default="shell")
    args = p.parse_args()
    try:
        r = resolve(args.branch, args.build_number)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(r))
    else:
        # Values are constrained to safe hostname/schema-style characters.
        for key, value in r.items():
            val = "true" if value is True else "false" if value is False else str(value)
            print(f"{key.upper()}={val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

=================================
=================================

#!/usr/bin/env python3
"""Create, reset or drop a single PostgreSQL schema safely.

Normal deployment:     provision_schema.py <schema>
Fresh test schema:     provision_schema.py <schema> --drop-first --yes
Final test cleanup:    provision_schema.py <schema> --drop-only --yes
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlparse, unquote

import psycopg2
from psycopg2 import sql

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,63}$")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def validate_identifier(value: str, label: str) -> None:
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise RuntimeError(f"Unsafe {label}: {value!r}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("schema")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--drop-first", action="store_true", help="Drop then recreate schema")
    group.add_argument("--drop-only", action="store_true", help="Drop schema and do not recreate")
    p.add_argument("--yes", action="store_true", help="Required for destructive operations")
    a = p.parse_args()
    if (a.drop_first or a.drop_only) and not a.yes:
        p.error("--drop-first/--drop-only require --yes")
    return a


def connection_kwargs() -> dict:
    # Prefer explicit selected DB variables. DB_ADMIN_URL is only a fallback for old jobs.
    if os.environ.get("DB_HOST"):
        return {
            "host": required("DB_HOST"),
            "port": int(os.environ.get("DB_PORT", "8080")),
            "dbname": required("DB_NAME"),
            "user": required("DB_ADMIN_USER"),
            "password": required("DB_ADMIN_PASS"),
            "connect_timeout": 15,
        }
    admin_url = os.environ.get("DB_ADMIN_URL", "").strip()
    if not admin_url:
        raise RuntimeError("DB_HOST/DB_NAME or DB_ADMIN_URL must be provided")
    parsed = urlparse(admin_url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/"),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 15,
    }


def main() -> int:
    args = parse_args()
    validate_identifier(args.schema, "schema")
    app_user = required("DB_APP_USER")
    validate_identifier(app_user, "application role")

    conn = psycopg2.connect(**connection_kwargs())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (app_user,))
            if not cur.fetchone():
                raise RuntimeError(f"Application DB role {app_user!r} does not exist")

            if args.drop_first or args.drop_only:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(args.schema)))
                print(f"Dropped schema: {args.schema}")

            if args.drop_only:
                conn.commit()
                return 0

            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(args.schema)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
                sql.Identifier(args.schema), sql.Identifier(app_user)))
            cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(
                sql.Identifier(args.schema), sql.Identifier(app_user)))
            cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                sql.Identifier(args.schema), sql.Identifier(app_user)))
            cur.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(sql.Identifier(args.schema), sql.Identifier(app_user)))
            cur.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(args.schema), sql.Identifier(app_user)))
        conn.commit()
        print(f"Schema ready: {args.schema}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: schema operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

=================================
=================================

#!/usr/bin/env python3
"""Nutanix VM lifecycle, Docker TLS renewal, deployment and deleted-branch cleanup.

Designed to keep Jenkinsfile-release readable while retaining existing behavior.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

STATE_DIR = Path(os.environ.get("NMDB_RELEASE_STATE", "/var/lib/nmdb-release"))
STATE_FILE = STATE_DIR / "branches.json"
LOCK_FILE = STATE_DIR / ".lock"
CERT_ROOT = Path(os.environ.get("DOCKER_TLS_ROOT", "/opt/docker-tls"))
CA_DIR = Path(os.environ.get("DOCKER_CA_DIR", "/opt/docker-ca"))


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def run(cmd, *, input_text=None, capture=False, timeout=300, env=None, check=True):
    proc = subprocess.run([str(x) for x in cmd], input=input_text, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None,
                          timeout=timeout, env=env)
    if check and proc.returncode:
        raise RuntimeError(f"Command failed ({Path(str(cmd[0])).name}, rc={proc.returncode})")
    return proc.stdout.strip() if capture else proc.returncode


def api(method: str, path: str, payload=None, missing_ok=False):
    host = required("PC_HOST")
    token = required("NTNX_SECRET")
    url = f"https://{host}:9440/api/nutanix/v3/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-ntnx-api-key": token, "Content-Type": "application/json"})
    verify = os.environ.get("PC_VERIFY_TLS", "false").lower() == "true"
    ctx = ssl.create_default_context(cafile=os.environ.get("PC_CA_FILE") or None) if verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=45) as res:
            body = res.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise RuntimeError(f"Nutanix API {method} {path} returned HTTP {exc.code}") from None


def wait_task(task_uuid: str, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api("GET", f"tasks/{task_uuid}")
        status = str(data.get("status", "")).upper()
        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "ABORTED", "CANCELLED"):
            raise RuntimeError(f"Nutanix task {task_uuid} ended with {status}")
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for Nutanix task {task_uuid}")


def task_uuid(response: dict) -> str:
    value = response.get("task_uuid") or response.get("status", {}).get("execution_context", {}).get("task_uuid")
    if not value:
        raise RuntimeError("Nutanix mutation returned no task UUID")
    return str(uuid.UUID(value))


def vm_name(vm: dict) -> str:
    return vm.get("spec", {}).get("name") or vm.get("status", {}).get("name") or ""


def list_vms():
    offset, all_vms = 0, []
    while True:
        page = api("POST", "vms/list", {"kind": "vm", "length": 500, "offset": offset})
        entities = page.get("entities", [])
        all_vms.extend(entities)
        total = int(page.get("metadata", {}).get("total_matches", len(all_vms)))
        if len(all_vms) >= total:
            return all_vms
        if not entities:
            raise RuntimeError("Incomplete Nutanix VM listing")
        offset += len(entities)


def get_ip(vm: dict) -> str | None:
    for nic in vm.get("status", {}).get("resources", {}).get("nic_list", []):
        for endpoint in nic.get("ip_endpoint_list", []):
            value = endpoint.get("ip")
            try:
                ip = ipaddress.ip_address(value)
                if ip.version == 4 and not ip.is_loopback and not ip.is_link_local:
                    return str(ip)
            except Exception:
                pass
    return None


def ensure_vm(name: str) -> tuple[str, str]:
    matches = [v for v in list_vms() if vm_name(v) == name]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Nutanix VMs found with name {name}; remove duplicates first")
    if matches:
        vm_uuid = matches[0]["metadata"]["uuid"]
    else:
        template = required("PC_TEMPLATE_VM_UUID")
        response = api("POST", f"vms/{template}/clone", {"override_spec": {"name": name}})
        result = wait_task(task_uuid(response))
        refs = [x.get("uuid") for x in result.get("entity_reference_list", []) if x.get("kind") == "vm"]
        refs = [x for x in refs if x and x != template]
        if len(refs) != 1:
            # Fallback to name lookup only after task completion.
            time.sleep(3)
            matches = [v for v in list_vms() if vm_name(v) == name]
            if len(matches) != 1:
                raise RuntimeError("Clone completed but new VM could not be identified safely")
            vm_uuid = matches[0]["metadata"]["uuid"]
        else:
            vm_uuid = refs[0]

    vm = api("GET", f"vms/{vm_uuid}")
    if str(vm.get("status", {}).get("resources", {}).get("power_state", "")).upper() != "ON":
        payload = {k: vm[k] for k in ("api_version", "metadata", "spec") if k in vm}
        payload.setdefault("spec", {}).setdefault("resources", {})["power_state"] = "ON"
        wait_task(task_uuid(api("PUT", f"vms/{vm_uuid}", payload)))

    deadline = time.time() + 1200
    while time.time() < deadline:
        vm = api("GET", f"vms/{vm_uuid}")
        ip = get_ip(vm)
        if ip:
            return vm_uuid, ip
        time.sleep(5)
    raise RuntimeError("VM did not receive a DHCP IPv4 address")


def openssl_cert_ok(cert: Path, key: Path, expected_ip: str, expected_dns: str, days=7) -> bool:
    if not cert.exists() or not key.exists():
        return False
    if subprocess.run(["openssl", "x509", "-checkend", str(days * 86400), "-noout", "-in", str(cert)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        return False
    text = run(["openssl", "x509", "-in", cert, "-noout", "-ext", "subjectAltName"], capture=True, check=False)
    if f"IP Address:{expected_ip}" not in text or f"DNS:{expected_dns}" not in text:
        return False
    cert_pub = run(["openssl", "x509", "-in", cert, "-pubkey", "-noout"], capture=True)
    key_pub = run(["openssl", "pkey", "-in", key, "-pubout"], capture=True)
    return cert_pub == key_pub


def client_cert_ok(cert: Path, key: Path, days=7) -> bool:
    if not cert.exists() or not key.exists():
        return False
    if subprocess.run(["openssl", "x509", "-checkend", str(days * 86400), "-noout", "-in", str(cert)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        return False
    return run(["openssl", "x509", "-in", cert, "-pubkey", "-noout"], capture=True) == \
           run(["openssl", "pkey", "-in", key, "-pubout"], capture=True)


def ensure_tls(vm_name_value: str, ip: str) -> tuple[Path, bool]:
    ca = CA_DIR / "ca.pem"
    ca_key = CA_DIR / "ca-key.pem"
    if not ca.exists() or not ca_key.exists():
        raise RuntimeError(f"Docker CA files missing under {CA_DIR}")
    # Leaf certificates can be renewed automatically. A near-expiry CA must be rotated deliberately
    # because every VM/client trusts the same CA; deleting the VM is not a real fix for an expired CA.
    if subprocess.run(["openssl", "x509", "-checkend", str(30 * 86400), "-noout", "-in", str(ca)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise RuntimeError("Docker CA certificate is expired or expires within 30 days; rotate /opt/docker-ca CA before deployment")
    fqdn = vm_name_value.replace("_", "-") + os.environ.get("VM_FQDN_SUFFIX", ".mcore")
    certdir = CERT_ROOT / vm_name_value
    certdir.mkdir(parents=True, exist_ok=True)
    server_cert, server_key = certdir / "server-cert.pem", certdir / "server-key.pem"
    client_cert, client_key = certdir / "cert.pem", certdir / "key.pem"
    renew = not openssl_cert_ok(server_cert, server_key, ip, fqdn) or not client_cert_ok(client_cert, client_key)
    if not renew:
        return certdir, False

    print(f"Docker TLS certificate missing/near expiry/IP changed; renewing for {vm_name_value} ({ip})")
    for path in certdir.glob("*"):
        if path.is_file():
            path.unlink()
    (certdir / "ca.pem").write_bytes(ca.read_bytes())

    server_ext = certdir / "server-ext.cnf"
    server_ext.write_text(f"extendedKeyUsage=serverAuth\nsubjectAltName=DNS:{fqdn},IP:{ip}\n")
    run(["openssl", "genrsa", "-out", server_key, "4096"])
    run(["openssl", "req", "-new", "-key", server_key, "-out", certdir / "server.csr", "-subj", f"/CN={fqdn}"])
    run(["openssl", "x509", "-req", "-days", "365", "-sha256", "-in", certdir / "server.csr",
         "-CA", ca, "-CAkey", ca_key, "-set_serial", "0x" + secrets.token_hex(16), "-out", server_cert, "-extfile", server_ext])

    client_ext = certdir / "client-ext.cnf"
    client_ext.write_text("extendedKeyUsage=clientAuth\n")
    run(["openssl", "genrsa", "-out", client_key, "4096"])
    run(["openssl", "req", "-new", "-key", client_key, "-out", certdir / "client.csr",
         "-subj", f"/CN=jenkins-{vm_name_value}"])
    run(["openssl", "x509", "-req", "-days", "365", "-sha256", "-in", certdir / "client.csr",
         "-CA", ca, "-CAkey", ca_key, "-set_serial", "0x" + secrets.token_hex(16), "-out", client_cert, "-extfile", client_ext])
    for p in (server_key, client_key):
        p.chmod(0o600)
    return certdir, True


def ssh_base(ip: str):
    user = required("SSH_USER")
    key = required("SSH_KEY")
    known = os.environ.get("SSH_KNOWN_HOSTS", "/var/lib/jenkins/.ssh/known_hosts")
    Path(known).parent.mkdir(parents=True, exist_ok=True)
    Path(known).touch(exist_ok=True)
    return ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={known}", f"{user}@{ip}"]


def scp_base(ip: str):
    user = required("SSH_USER")
    key = required("SSH_KEY")
    known = os.environ.get("SSH_KNOWN_HOSTS", "/var/lib/jenkins/.ssh/known_hosts")
    return ["scp", "-i", key, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={known}"]


def configure_remote_docker(ip: str, certdir: Path, force_restart: bool):
    base = ssh_base(ip)
    # Wait for SSH/template initialization.
    deadline = time.time() + 300
    while time.time() < deadline:
        if subprocess.run(base + ["sudo -n true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(5)
    else:
        raise RuntimeError("SSH/passwordless sudo did not become ready")

    user = required("SSH_USER")
    target = f"{user}@{ip}:/tmp/"
    for local, remote in ((certdir / "server-cert.pem", "server-cert.pem"), (certdir / "server-key.pem", "server-key.pem"), (certdir / "ca.pem", "ca.pem")):
        run(scp_base(ip) + [local, target + remote])

    registry = required("HARBOR_HOST")
    tls_port = os.environ.get("DOCKER_TLS_PORT", "8443")
    remote_script = f'''set -euo pipefail
sudo -n mkdir -p /etc/docker/ssl /etc/systemd/system/docker.service.d /opt/nmdb-logs /opt/nmdb-exports
sudo -n chmod 777 /opt/nmdb-logs /opt/nmdb-exports
sudo -n install -m 600 /tmp/server-cert.pem /etc/docker/ssl/server-cert.pem
sudo -n install -m 600 /tmp/server-key.pem /etc/docker/ssl/server-key.pem
sudo -n install -m 600 /tmp/ca.pem /etc/docker/ssl/ca.pem
python3 - <<'PYREMOTE'
import json
from pathlib import Path
p=Path('/tmp/daemon.json.new')
old=Path('/etc/docker/daemon.json')
d=json.loads(old.read_text()) if old.exists() and old.read_text().strip() else {{}}
r=d.setdefault('insecure-registries', [])
if {registry!r} not in r: r.append({registry!r})
p.write_text(json.dumps(d, indent=2)+'\\n')
PYREMOTE
sudo -n install -m 644 /tmp/daemon.json.new /etc/docker/daemon.json
cat >/tmp/nmdb-docker-override.conf <<'EOFREMOTE'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H unix:///var/run/docker.sock -H tcp://0.0.0.0:{tls_port} --tlsverify --tlscacert=/etc/docker/ssl/ca.pem --tlscert=/etc/docker/ssl/server-cert.pem --tlskey=/etc/docker/ssl/server-key.pem
EOFREMOTE
sudo -n install -m 644 /tmp/nmdb-docker-override.conf /etc/systemd/system/docker.service.d/nmdb-tls.conf
sudo -n systemctl daemon-reload
sudo -n systemctl restart docker
sudo -n systemctl is-active --quiet docker
'''
    # Restart is intentionally done whenever this stage runs: it also repairs a stale/expired remote cert.
    run(base + ["bash", "-lc", shlex.quote(remote_script)], timeout=180)


def docker_cmd(ip: str, certdir: Path):
    port = os.environ.get("DOCKER_TLS_PORT", "8443")
    return ["docker", "--host", f"tcp://{ip}:{port}", "--tlsverify",
            "--tlscacert", certdir / "ca.pem", "--tlscert", certdir / "cert.pem", "--tlskey", certdir / "key.pem"]


def deploy(ip: str, certdir: Path, vm_name_value: str):
    registry = required("HARBOR_HOST")
    full_image = required("FULL_IMAGE")
    container_port = os.environ.get("CONTAINER_PORT", "8080")
    host_port = os.environ.get("HOST_PORT", "8080")
    dcmd = docker_cmd(ip, certdir)

    with tempfile.TemporaryDirectory(prefix="nmdb-docker-") as dc:
        env = dict(os.environ)
        env["DOCKER_CONFIG"] = dc
        # Auth config is local, pull is executed by the target daemon through TLS.
        run(["docker", "login", f"http://{registry}", "-u", required("HUSER"), "--password-stdin"],
            input_text=required("HPASS") + "\n", env=env)
        run(dcmd + ["pull", full_image], env=env, timeout=900)

        # Refuse to kill a different container that happens to use the same host port.
        conflict = run(dcmd + ["ps", "-q", "--filter", f"publish={host_port}"], capture=True, env=env, check=False)
        old_id = run(dcmd + ["ps", "-aq", "--filter", f"name=^/{vm_name_value}$"], capture=True, env=env, check=False)
        if conflict and (not old_id or conflict.strip() != old_id.strip()):
            raise RuntimeError(f"Port {host_port} is occupied by an unrelated container; refusing to remove it")

        rollback = vm_name_value + "-rollback"
        if run(dcmd + ["ps", "-aq", "--filter", f"name=^/{rollback}$"], capture=True, env=env, check=False):
            raise RuntimeError(f"Rollback container {rollback} already exists; reconcile it before redeploying")

        if old_id:
            run(dcmd + ["stop", "--time", "30", vm_name_value], env=env)
            run(dcmd + ["rename", vm_name_value, rollback], env=env)

        encoded_db_url = required("DATABASE_URL")
        envfile = Path(dc) / "application.env"
        values = {
            "DATABASE_URL": encoded_db_url,
            "NEC_SCHEMA": required("NEC_SCHEMA"),
            "ENVIRONMENT": os.environ.get("APP_ENVIRONMENT", "dev"),
            "EXPORT_STORAGE_ROOT": "/app/exports",
            "EXPORT_DOWNLOAD_BASE_URL": f"http://{ip}:{host_port}",
        }
        if any("\n" in v or "\r" in v for v in values.values()):
            raise RuntimeError("Application environment contains an invalid newline")
        envfile.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        envfile.chmod(0o600)
        run(dcmd + ["run", "-d", "--restart", "unless-stopped", "--name", vm_name_value,
                    "-p", f"{host_port}:{container_port}", "--env-file", envfile,
                    "-v", "/opt/nmdb-logs:/app/logs", "-v", "/opt/nmdb-exports:/app/exports",
                    full_image], env=env)

        # Basic readiness: container must remain running. Optional HTTP health path can strengthen it.
        deadline = time.time() + 120
        health_path = os.environ.get("APP_HEALTH_PATH", "").strip()
        success = False
        while time.time() < deadline:
            running = run(dcmd + ["inspect", "-f", "{{.State.Running}}", vm_name_value], capture=True, env=env, check=False)
            if running.strip() == "true":
                if not health_path:
                    success = True
                    break
                try:
                    with urllib.request.urlopen(f"http://{ip}:{host_port}{health_path}", timeout=5) as res:
                        if 200 <= res.status < 400:
                            success = True
                            break
                except Exception:
                    pass
            time.sleep(3)
        if not success:
            run(dcmd + ["rm", "-f", vm_name_value], env=env, check=False)
            if old_id:
                run(dcmd + ["rename", rollback, vm_name_value], env=env)
                run(dcmd + ["start", vm_name_value], env=env)
            raise RuntimeError("New application container did not become ready; previous container restored")
        if old_id:
            run(dcmd + ["rm", rollback], env=env)
        run(["docker", "logout", registry], env=env, check=False)


def lock_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = LOCK_FILE.open("a+")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def record(branch, vm_uuid, ip, vm_name_value, db_host, db_name, schema):
    with lock_state():
        state = load_state()
        state[branch] = {"vm_uuid": vm_uuid, "ip": ip, "vm_name": vm_name_value,
                         "db_host": db_host, "db_name": db_name, "schema": schema, "updated": int(time.time())}
        save_state(state)


def delete_vm(vm_uuid: str, expected_name: str):
    if vm_uuid == os.environ.get("PC_TEMPLATE_VM_UUID"):
        raise RuntimeError("Refusing to delete configured template VM")
    vm = api("GET", f"vms/{vm_uuid}", missing_ok=True)
    if not vm:
        return
    if vm_name(vm) != expected_name:
        raise RuntimeError(f"VM UUID/name mismatch; refusing delete ({vm_uuid})")
    wait_task(task_uuid(api("DELETE", f"vms/{vm_uuid}")))


def remote_branches(repo_url: str) -> set[str]:
    user, token = required("BB_USER"), required("BB_TOKEN")
    with tempfile.TemporaryDirectory() as td:
        ask = Path(td) / "askpass"
        ask.write_text('#!/bin/sh\ncase "$1" in *Username*) printf "%s" "$BB_USER";; *) printf "%s" "$BB_TOKEN";; esac\n')
        ask.chmod(0o700)
        env = {**os.environ, "GIT_ASKPASS": str(ask), "GIT_TERMINAL_PROMPT": "0"}
        out = run(["git", "ls-remote", "--heads", repo_url], capture=True, timeout=90, env=env)
    branches = {line.split("\t", 1)[1].removeprefix("refs/heads/") for line in out.splitlines() if "\trefs/heads/" in line}
    if not branches:
        raise RuntimeError("Git returned zero branches; cleanup refuses to treat this as branch deletion")
    return branches


def cleanup_deleted():
    repo = required("SCM_URL")
    live = remote_branches(repo)
    protected = {"main"}
    grace = int(os.environ.get("BRANCH_DELETE_GRACE", "3600"))
    now = int(time.time())
    with lock_state():
        state = load_state()
        changed = False
        for branch, rec in list(state.items()):
            if branch in protected or branch in live:
                if rec.pop("absent_since", None) is not None:
                    changed = True
                continue
            if "absent_since" not in rec:
                rec["absent_since"] = now
                changed = True
                print(f"Branch absent: {branch}; retirement grace started")
                continue
            if now - int(rec["absent_since"]) < grace:
                continue

            # Recheck immediately before destructive actions.
            if branch in remote_branches(repo):
                rec.pop("absent_since", None)
                changed = True
                continue
            print(f"Retiring deleted branch {branch}: VM {rec.get('vm_name')}, schema {rec.get('schema')}")
            delete_vm(rec["vm_uuid"], rec["vm_name"])
            # A recreated branch must keep its data even if VM retirement just completed.
            if branch in remote_branches(repo):
                raise RuntimeError(f"Branch {branch} reappeared during cleanup; schema deletion stopped")
            # Drop only the exact persistent branch schemas after VM deletion.
            helper = Path(__file__).with_name("provision_schema.py")
            cleanup_env = dict(os.environ)
            cleanup_env.update({
                "DB_HOST": rec["db_host"], "DB_PORT": "8080", "DB_NAME": rec["db_name"],
                "DB_APP_USER": required("NMDB_APP_USER")
            })
            run([sys.executable, helper, rec["schema"], "--drop-only", "--yes"], env=cleanup_env)
            run([sys.executable, helper, rec["schema"] + "_nec", "--drop-only", "--yes"], env=cleanup_env)
            certdir = CERT_ROOT / rec.get("vm_name", "")
            if certdir.is_dir():
                for f in certdir.iterdir():
                    if f.is_file(): f.unlink()
                try: certdir.rmdir()
                except OSError: pass
            state.pop(branch, None)
            changed = True
        if changed:
            save_state(state)



def finalize_cleanup(branch: str):
    with lock_state():
        state = load_state()
        rec = state.get(branch)
        if rec and rec.get("vm_deleted"):
            certdir = CERT_ROOT / rec.get("vm_name", "")
            if certdir.is_dir():
                for f in certdir.iterdir():
                    if f.is_file(): f.unlink()
                try: certdir.rmdir()
                except OSError: pass
            state.pop(branch, None)
            save_state(state)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensure-vm"); e.add_argument("--name", required=True)
    t = sub.add_parser("tls"); t.add_argument("--name", required=True); t.add_argument("--ip", required=True)
    d = sub.add_parser("deploy"); d.add_argument("--name", required=True); d.add_argument("--ip", required=True)
    r = sub.add_parser("record"); r.add_argument("--branch", required=True); r.add_argument("--vm-uuid", required=True); r.add_argument("--ip", required=True); r.add_argument("--name", required=True); r.add_argument("--db-host", required=True); r.add_argument("--db-name", required=True); r.add_argument("--schema", required=True)
    sub.add_parser("cleanup-deleted")
    f = sub.add_parser("finalize-cleanup"); f.add_argument("--branch", required=True)
    a = p.parse_args()
    if a.cmd == "ensure-vm":
        vm_uuid, ip = ensure_vm(a.name); print(f"VM_UUID={vm_uuid}\nTARGET_VM_IP={ip}")
    elif a.cmd == "tls":
        certdir, renewed = ensure_tls(a.name, a.ip); configure_remote_docker(a.ip, certdir, renewed); print(f"TLS_DIR={certdir}")
    elif a.cmd == "deploy":
        certdir, _ = ensure_tls(a.name, a.ip); deploy(a.ip, certdir, a.name)
    elif a.cmd == "record": record(a.branch, a.vm_uuid, a.ip, a.name, a.db_host, a.db_name, a.schema)
    elif a.cmd == "cleanup-deleted": cleanup_deleted()
    elif a.cmd == "finalize-cleanup": finalize_cleanup(a.branch)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

=================================
=================================

// NMDB BUILD PIPELINE
// Branch push -> build/test -> image push -> NMDB-RELEASE
// PR opened/updated: disable PR discovery in Multibranch job; changeRequest() is a second guard.

def notifyBitbucket(String state) {
    if (!env.GIT_COMMIT?.trim()) return
    catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE', catchInterruptions: false) {
        withCredentials([usernamePassword(credentialsId: 'bitbucket-build-status', usernameVariable: 'BB_USER', passwordVariable: 'BB_TOKEN')]) {
            sh """#!/usr/bin/env bash
                set +x
                set -euo pipefail
                curl -fsS -X POST \\
                  -u \"\${BB_USER}:\${BB_TOKEN}\" \\
                  -H 'Content-Type: application/json' \\
                  -d '{
                    "state": "${state}",
                    "key": "jenkins-ci",
                    "name": "${env.JOB_NAME} #${env.BUILD_NUMBER}",
                    "url": "${env.BUILD_URL}",
                    "description": "NMDB Jenkins ${state}"
                  }' \\
                  "https://bitbucket-uae.l3harris.com:8443/rest/build-status/1.0/commits/${env.GIT_COMMIT}"
            """
        }
    }
}

pipeline {
    agent none

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 150, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    environment {
        HARBOR_HOST    = '10.192.25.39:80'
        HARBOR_PROJECT = 'newsc'
        APP_NAME       = 'nmdb-app'
        PIPELINE_PY    = 'scripts/pipeline_utils.py'
        SCHEMA_PY      = 'scripts/provision_schema.py'
    }

    stages {
        stage('Branch Build') {
            when {
                beforeAgent true
                not { changeRequest() }
            }
            agent { label 'newsc-agent-1' }

            stages {
                stage('Checkout') {
                    steps {
                        deleteDir()
                        checkout scm
                        script {
                            env.GIT_COMMIT = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
                            env.SOURCE_BRANCH = env.BRANCH_NAME
                        }
                        script { notifyBitbucket('INPROGRESS') }
                    }
                }

                stage('Resolve Branch / Database') {
                    steps {
                        script {
                            def output = sh(
                                returnStdout: true,
                                script: "python3 ${env.PIPELINE_PY} --branch '${env.SOURCE_BRANCH.replace("'", "'\\''")}' --build-number '${env.BUILD_NUMBER}' --format shell"
                            ).trim()
                            output.readLines().each { line ->
                                def pair = line.split('=', 2)
                                if (pair.size() == 2) env[pair[0]] = pair[1]
                            }
                            env.IMAGE_TAG = "${env.SLUG}-${env.BUILD_NUMBER}"
                            env.FULL_IMAGE = "${env.HARBOR_HOST}/${env.HARBOR_PROJECT}/${env.APP_NAME}:${env.IMAGE_TAG}"
                            env.BRANCH_LATEST = "${env.HARBOR_HOST}/${env.HARBOR_PROJECT}/${env.APP_NAME}:${env.SLUG}-latest"
                            echo "Branch=${env.BRANCH} staging=${env.IS_STAGING} DB=${env.DB_HOST}:${env.DB_PORT}/${env.DB_NAME} TEST_SCHEMA=${env.TEST_SCHEMA}"
                        }
                    }
                }

                stage('Verify Offline Wheels') {
                    steps {
                        sh '''#!/usr/bin/env bash
                            set -euo pipefail
                            test -f requirements.txt
                            test -d wheels
                            echo "Wheel count: $(find wheels -maxdepth 1 -type f | wc -l)"
                        '''
                    }
                }

                stage('Setup Python Environment') {
                    steps {
                        sh '''#!/usr/bin/env bash
                            set -euo pipefail
                            rm -rf .venv
                            python3 -m venv .venv
                            . .venv/bin/activate
                            pip install --quiet --no-index --find-links=wheels -r requirements-dev.txt
                            echo "Python: $(python --version)"
                            echo "Pytest: $(pytest --version | head -1)"
                        '''
                    }
                }

                stage('Static Analysis - Prospector') {
                    steps {
                        sh '''#!/usr/bin/env bash
                            set +e
                            . .venv/bin/activate
                            pip install --quiet --no-index --find-links=wheels prospector
                            prospector app/ --output-format json --ignore-paths alembic --ignore-paths tests > prospector.json 2>prospector.log
                            RC=$?
                            echo "Prospector exit code: $RC (advisory, does not block deployment)"
                            exit 0
                        '''
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'prospector.json,prospector.log', allowEmptyArchive: true
                        }
                    }
                }

                stage('Provision Fresh Test Schemas') {
                    steps {
                        withCredentials([
                            usernamePassword(credentialsId: 'nmdb-db-admin', usernameVariable: 'DB_ADMIN_USER', passwordVariable: 'DB_ADMIN_PASS'),
                            usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')
                        ]) {
                            sh '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                . .venv/bin/activate
                                export DB_APP_USER="$NMDB_APP_USER"
                                python "$SCHEMA_PY" "$TEST_SCHEMA" --drop-first --yes
                                python "$SCHEMA_PY" "${TEST_SCHEMA}_nec" --drop-first --yes
                            '''
                        }
                    }
                }

                stage('Migrate Test Schemas') {
                    steps {
                        withCredentials([usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')]) {
                            sh '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                . .venv/bin/activate
                                ENCODED_PASS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$NMDB_APP_PASS")
                                ENCODED_OPTIONS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote("-csearch_path="+sys.argv[1]+","+sys.argv[1]+"_nec", safe=""))' "$TEST_SCHEMA")
                                export DATABASE_URL="postgresql://${NMDB_APP_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=${ENCODED_OPTIONS}"
                                export TEST_DATABASE_URL="$DATABASE_URL"
                                export TESTING=1
                                alembic upgrade head
                                echo "Test migrations applied to ${DB_NAME}/${TEST_SCHEMA}"
                            '''
                        }
                    }
                }

                stage('Run Tests') {
                    steps {
                        withCredentials([usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')]) {
                            sh '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                . .venv/bin/activate
                                mkdir -p test-results
                                ENCODED_PASS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$NMDB_APP_PASS")
                                ENCODED_OPTIONS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote("-csearch_path="+sys.argv[1]+","+sys.argv[1]+"_nec", safe=""))' "$TEST_SCHEMA")
                                export DATABASE_URL="postgresql://${NMDB_APP_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=${ENCODED_OPTIONS}"
                                export TEST_DATABASE_URL="$DATABASE_URL"
                                export TESTING=1
                                echo "Testing ${DB_HOST}:${DB_PORT}/${DB_NAME}; schema=${TEST_SCHEMA}"
                                python -m pytest tests/ \\
                                  --tb=short -vv --durations=10 \\
                                  --junitxml=test-results/junit.xml \\
                                  --cov=app --cov-report=html:coverage-html --cov-report=xml:coverage.xml
                            '''
                        }
                    }
                    post {
                        always {
                            script {
                                if (fileExists('test-results/junit.xml')) {
                                    junit testResults: 'test-results/junit.xml'
                                }
                            }
                            archiveArtifacts artifacts: 'coverage.xml,coverage-html/**,test-results/**', allowEmptyArchive: true
                        }
                    }
                }

                stage('Build Docker Image') {
                    steps {
                        sh '''#!/usr/bin/env bash
                            set -euo pipefail
                            docker build \\
                              --label branch="$SOURCE_BRANCH" \\
                              --label build="$BUILD_NUMBER" \\
                              --label commit="$GIT_COMMIT" \\
                              --label org.opencontainers.image.revision="$GIT_COMMIT" \\
                              -t "$FULL_IMAGE" .
                            docker tag "$FULL_IMAGE" "$BRANCH_LATEST"
                        '''
                    }
                }

                stage('Push to Harbor') {
                    steps {
                        withCredentials([usernamePassword(credentialsId: 'Harbor', usernameVariable: 'HUSER', passwordVariable: 'HPASS')]) {
                            sh '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                printf '%s' "$HPASS" | docker login "$HARBOR_HOST" -u "$HUSER" --password-stdin
                                docker push "$FULL_IMAGE"
                                docker push "$BRANCH_LATEST"
                                docker logout "$HARBOR_HOST" || true
                            '''
                        }
                    }
                }
            }

            post {
                always {
                    // Drop-only cleanup: never recreates test schemas.
                    catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE', catchInterruptions: false) {
                        withCredentials([
                            usernamePassword(credentialsId: 'nmdb-db-admin', usernameVariable: 'DB_ADMIN_USER', passwordVariable: 'DB_ADMIN_PASS'),
                            usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')
                        ]) {
                            sh '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                if [[ -n "${TEST_SCHEMA:-}" && -x .venv/bin/python ]]; then
                                  export DB_APP_USER="$NMDB_APP_USER"
                                  .venv/bin/python "$SCHEMA_PY" "$TEST_SCHEMA" --drop-only --yes
                                  .venv/bin/python "$SCHEMA_PY" "${TEST_SCHEMA}_nec" --drop-only --yes
                                fi
                            '''
                        }
                    }
                }
            }
        }

        stage('Trigger Release') {
            when {
                beforeAgent true
                not { changeRequest() }
            }
            steps {
                // Normal parameterized Pipeline job. No Jenkins.instance/scheduleBuild2/script approval.
                build job: 'NMDB-RELEASE', wait: true, propagate: true, parameters: [
                    string(name: 'IMAGE_TAG', value: env.IMAGE_TAG),
                    string(name: 'SOURCE_BRANCH', value: env.SOURCE_BRANCH),
                    string(name: 'GIT_COMMIT', value: env.GIT_COMMIT)
                ]
            }
        }
    }

    post {
        success { script { if (env.GIT_COMMIT) { node('newsc-agent-1') { notifyBitbucket('SUCCESSFUL') } } } }
        failure { script { if (env.GIT_COMMIT) { node('newsc-agent-1') { notifyBitbucket('FAILED') } } } }
        aborted { script { if (env.GIT_COMMIT) { node('newsc-agent-1') { notifyBitbucket('FAILED') } } } }
    }
}

=================================
=================================

// NMDB RELEASE PIPELINE
// Use as ONE normal parameterized Jenkins Pipeline job named NMDB-RELEASE.
// Upstream build supplies IMAGE_TAG, SOURCE_BRANCH and GIT_COMMIT.
// Timer runs branch-deletion cleanup only when IMAGE_TAG is blank.

pipeline {
    agent { label 'newsc-agent-1' }

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 120, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '50'))
    }

    triggers {
        cron('H/15 * * * *')
    }

    parameters {
        string(name: 'IMAGE_TAG', defaultValue: '', description: 'Set by NMDB-BUILD. Blank timer run = deleted-branch cleanup only.')
        string(name: 'SOURCE_BRANCH', defaultValue: 'main')
        string(name: 'GIT_COMMIT', defaultValue: '')
        string(name: 'HOST_PORT', defaultValue: '8080')
        string(name: 'CONTAINER_PORT', defaultValue: '8080')
        string(name: 'DOCKER_TLS_PORT', defaultValue: '8443')
        string(name: 'PC_HOST', defaultValue: '10.192.24.59')
        string(name: 'PC_CLUSTER_UUID', defaultValue: 'e00649fa-1fc5-7223-35cf-5e8aca40ad3b')
        string(name: 'PC_SUBNET_UUID', defaultValue: '28f2fbf8-b8bf-4eac-827f-889d94acd99d')
        string(name: 'PC_TEMPLATE_VM_UUID', defaultValue: 'a915b4cf-7bf3-4eef-851e-9b8d46a9179f')
        string(name: 'VM_FQDN_SUFFIX', defaultValue: '.mcore')
        string(name: 'APP_HEALTH_PATH', defaultValue: '', description: 'Optional, e.g. /health. Blank = verify container stays running.')
    }

    environment {
        HARBOR_HOST    = '10.192.25.39:80'
        HARBOR_PROJECT = 'newsc'
        APP_NAME       = 'nmdb-app'
        SCM_URL        = 'https://bitbucket-uae.l3harris.com:8443/scm/newsc/nmdb.git'
        PIPELINE_PY    = 'scripts/pipeline_utils.py'
        SCHEMA_PY      = 'scripts/provision_schema.py'
        RELEASE_PY     = 'scripts/release_manager.py'
        DOCKER_CA_DIR  = '/opt/docker-ca'
        DOCKER_TLS_ROOT = '/opt/docker-tls'
        NMDB_RELEASE_STATE = '/var/lib/nmdb-release'
    }

    stages {
        stage('Deleted Branch Cleanup') {
            when {
                expression { return !params.IMAGE_TAG?.trim() }
            }
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'bitbucket-build-status', usernameVariable: 'BB_USER', passwordVariable: 'BB_TOKEN'),
                    usernamePassword(credentialsId: 'nutanix_api_key', usernameVariable: 'NTNX_KEY', passwordVariable: 'NTNX_SECRET'),
                    usernamePassword(credentialsId: 'nmdb-db-admin', usernameVariable: 'DB_ADMIN_USER', passwordVariable: 'DB_ADMIN_PASS'),
                    usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')
                ]) {
                    withEnv([
                        "PC_HOST=${params.PC_HOST}",
                        "PC_CLUSTER_UUID=${params.PC_CLUSTER_UUID}",
                        "PC_SUBNET_UUID=${params.PC_SUBNET_UUID}",
                        "PC_TEMPLATE_VM_UUID=${params.PC_TEMPLATE_VM_UUID}"
                    ]) {
                        sh '''#!/usr/bin/env bash
                            set +x
                            set -euo pipefail
                            python3 "$RELEASE_PY" cleanup-deleted
                        '''
                    }
                }
            }
        }

        stage('Validate Trigger') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                script {
                    if (!params.SOURCE_BRANCH?.trim() || !params.GIT_COMMIT?.trim()) {
                        error('SOURCE_BRANCH and GIT_COMMIT are mandatory for deployment')
                    }
                    if (!(params.GIT_COMMIT ==~ /[0-9a-fA-F]{40}/)) {
                        error('GIT_COMMIT must be a complete 40-character SHA')
                    }
                }
            }
        }

        stage('Checkout Exact Source Commit') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                deleteDir()
                checkout([$class: 'GitSCM',
                    branches: [[name: params.GIT_COMMIT]],
                    doGenerateSubmoduleConfigurations: false,
                    extensions: [[$class: 'CloneOption', noTags: true, shallow: false]],
                    userRemoteConfigs: [[url: env.SCM_URL, credentialsId: 'bitbucket-build-status']]
                ])
            }
        }

        stage('Resolve Branch / VM / Database') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                script {
                    def output = sh(returnStdout: true,
                        script: "python3 ${env.PIPELINE_PY} --branch '${params.SOURCE_BRANCH.replace("'", "'\\''")}' --format shell").trim()
                    output.readLines().each { line ->
                        def pair = line.split('=', 2)
                        if (pair.size() == 2) env[pair[0]] = pair[1]
                    }
                    env.FULL_IMAGE = "${env.HARBOR_HOST}/${env.HARBOR_PROJECT}/${env.APP_NAME}:${params.IMAGE_TAG}"
                    // Preserve current application behavior; staging separation is DB/schema based.
                    env.APP_ENVIRONMENT = 'dev'
                    echo "Release branch=${env.BRANCH}; VM=${env.VM_NAME}; DB=${env.DB_HOST}:${env.DB_PORT}/${env.DB_NAME}; schema=${env.DEPLOY_SCHEMA}"
                }
            }
        }

        stage('Ensure Nutanix VM and Get IP') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                withCredentials([usernamePassword(credentialsId: 'nutanix_api_key', usernameVariable: 'NTNX_KEY', passwordVariable: 'NTNX_SECRET')]) {
                    script {
                        withEnv([
                            "PC_HOST=${params.PC_HOST}",
                            "PC_CLUSTER_UUID=${params.PC_CLUSTER_UUID}",
                            "PC_SUBNET_UUID=${params.PC_SUBNET_UUID}",
                            "PC_TEMPLATE_VM_UUID=${params.PC_TEMPLATE_VM_UUID}"
                        ]) {
                            def out = sh(returnStdout: true, script: '''#!/usr/bin/env bash
                                set +x
                                set -euo pipefail
                                python3 "$RELEASE_PY" ensure-vm --name "$VM_NAME"
                            ''').trim()
                            out.readLines().each { line ->
                                def pair = line.split('=', 2)
                                if (pair.size() == 2 && ['VM_UUID','TARGET_VM_IP'].contains(pair[0])) env[pair[0]] = pair[1]
                            }
                            if (!env.VM_UUID || !env.TARGET_VM_IP) error('Nutanix VM UUID/IP was not resolved')
                            sh '''#!/usr/bin/env bash
                                set -euo pipefail
                                python3 "$RELEASE_PY" record --branch "$BRANCH" --vm-uuid "$VM_UUID" --ip "$TARGET_VM_IP" --name "$VM_NAME" --db-host "$DB_HOST" --db-name "$DB_NAME" --schema "$DEPLOY_SCHEMA"
                            '''
                        }
                    }
                }
            }
        }

        stage('Provision Deployment Schemas') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'nmdb-db-admin', usernameVariable: 'DB_ADMIN_USER', passwordVariable: 'DB_ADMIN_PASS'),
                    usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')
                ]) {
                    sh '''#!/usr/bin/env bash
                        set +x
                        set -euo pipefail
                        if [[ ! -x .venv/bin/python ]]; then
                          python3 -m venv .venv
                          . .venv/bin/activate
                          pip install --quiet --no-index --find-links=wheels -r requirements.txt
                          pip install --quiet --no-index --find-links=wheels psycopg2-binary
                        else
                          . .venv/bin/activate
                        fi
                        export DB_APP_USER="$NMDB_APP_USER"
                        python "$SCHEMA_PY" "$DEPLOY_SCHEMA"
                        python "$SCHEMA_PY" "${DEPLOY_SCHEMA}_nec"
                    '''
                }
            }
        }

        stage('Migrate Deployment Schema') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                withCredentials([usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')]) {
                    sh '''#!/usr/bin/env bash
                        set +x
                        set -euo pipefail
                        . .venv/bin/activate
                        ENCODED_PASS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$NMDB_APP_PASS")
                        ENCODED_OPTIONS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote("-csearch_path="+sys.argv[1]+","+sys.argv[1]+"_nec", safe=""))' "$DEPLOY_SCHEMA")
                        export DATABASE_URL="postgresql://${NMDB_APP_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=${ENCODED_OPTIONS}"
                        alembic upgrade head
                        echo "Migration complete: ${DB_NAME}/${DEPLOY_SCHEMA}"
                    '''
                }
            }
        }

        stage('Docker TLS - Validate / Renew / Configure VM') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                withCredentials([sshUserPrivateKey(credentialsId: 'NMDB_DEPLOY_SSH', keyFileVariable: 'SSH_KEY', usernameVariable: 'SSH_USER')]) {
                    withEnv([
                        "DOCKER_TLS_PORT=${params.DOCKER_TLS_PORT}",
                        "VM_FQDN_SUFFIX=${params.VM_FQDN_SUFFIX}"
                    ]) {
                        sh '''#!/usr/bin/env bash
                            set +x
                            set -euo pipefail
                            python3 "$RELEASE_PY" tls --name "$VM_NAME" --ip "$TARGET_VM_IP"
                        '''
                    }
                }
            }
        }

        stage('Deploy from Harbor via Docker TLS') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'Harbor', usernameVariable: 'HUSER', passwordVariable: 'HPASS'),
                    usernamePassword(credentialsId: 'nmdb-db-app', usernameVariable: 'NMDB_APP_USER', passwordVariable: 'NMDB_APP_PASS')
                ]) {
                    withEnv([
                        "HOST_PORT=${params.HOST_PORT}",
                        "CONTAINER_PORT=${params.CONTAINER_PORT}",
                        "DOCKER_TLS_PORT=${params.DOCKER_TLS_PORT}",
                        "APP_HEALTH_PATH=${params.APP_HEALTH_PATH}"
                    ]) {
                        sh '''#!/usr/bin/env bash
                            set +x
                            set -euo pipefail
                            ENCODED_PASS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$NMDB_APP_PASS")
                            ENCODED_OPTIONS=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote("-csearch_path="+sys.argv[1]+","+sys.argv[1]+"_nec", safe=""))' "$DEPLOY_SCHEMA")
                            export DATABASE_URL="postgresql://${NMDB_APP_USER}:${ENCODED_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?options=${ENCODED_OPTIONS}"
                            export NEC_SCHEMA="${DEPLOY_SCHEMA}_nec"
                            python3 "$RELEASE_PY" deploy --name "$VM_NAME" --ip "$TARGET_VM_IP"
                        '''
                    }
                }
            }
        }

        stage('Record Branch Resources') {
            when { expression { return params.IMAGE_TAG?.trim() } }
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    python3 "$RELEASE_PY" record \
                      --branch "$BRANCH" --vm-uuid "$VM_UUID" --ip "$TARGET_VM_IP" --name "$VM_NAME" \
                      --db-host "$DB_HOST" --db-name "$DB_NAME" --schema "$DEPLOY_SCHEMA"
                '''
            }
        }
    }
}
