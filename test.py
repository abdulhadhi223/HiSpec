PostgreSQL & pgAdmin – Staging Environment Setup
1. Overview
A dedicated PostgreSQL and pgAdmin environment was created for the staging application and performance/load testing.
Component	Configuration
Host OS	Rocky Linux
PostgreSQL	18.6 Bookworm
PostgreSQL port	8080 → 5432
pgAdmin port	80 → 80
Database	nmdb_staging
PostgreSQL data path	/opt/postgres-staging/data
Deployment	Docker Compose
Registry	Internal Harbor
TLS/SSL	Not enabled currently


The PostgreSQL image was pulled externally, transferred to the internal environment, and pushed to Harbor.
docker tag postgres:18.6-bookworm \
  <harbor>/base-images/postgres:18.6-bookworm

docker push \
  <harbor>/base-images/postgres:18.6-bookworm

The Docker Compose file is maintained in Bitbucket.
2. Directory & Persistent Storage
The staging setup is maintained under:
/opt/postgres-staging/
├── compose.yaml
├── .env
└── data/

PostgreSQL uses the host path:
/opt/postgres-staging/data
        ↓
/var/lib/postgresql

On Rocky Linux, SELinux support is enabled using:
volumes:
  - /opt/postgres-staging/data:/var/lib/postgresql:Z

Required directory permissions:
sudo mkdir -p /opt/postgres-staging/data
sudo chown 999:999 /opt/postgres-staging/data
sudo chmod 700 /opt/postgres-staging/data

pgAdmin uses a Docker named volume for its persistent configuration.
3. Environment Configuration
Credentials and image references are stored in .env.
Example:
POSTGRES_IMAGE=<harbor>/base-images/postgres:18.6-bookworm
POSTGRES_USER=<staging-user>
POSTGRES_PASSWORD=<password>
POSTGRES_DB=nmdb_staging

PGADMIN_IMAGE=<harbor>/base-images/pgadmin4:<tag>
PGADMIN_DEFAULT_EMAIL=<email>
PGADMIN_DEFAULT_PASSWORD=<password>

Restrict access to the file:
chmod 600 .env

Credentials must not be committed to Bitbucket.
4. Start the Environment
From:
cd /opt/postgres-staging

Validate the Compose file:
docker compose -f compose.yaml config --quiet

Start the containers:
docker compose -f compose.yaml up -d

Check status:
docker compose -f compose.yaml ps

Check PostgreSQL logs if required:
docker compose -f compose.yaml logs --tail=100 db

Expected PostgreSQL status:
database system is ready to accept connections

The Compose configuration also includes:
- PostgreSQL health check using pg_isready
- Docker log rotation
- pgAdmin dependency on PostgreSQL health
5. Connection Details
Application / Jenkins
Applications outside the Docker network connect through:
Host: <STAGING_VM_IP>
Port: 8080
Database: nmdb_staging

pgAdmin
Open:
http://<STAGING_VM_IP>

Register the PostgreSQL server using:
Setting	Value
Host	db
Port	5432
Database	nmdb_staging
Username	PostgreSQL staging user
Password	PostgreSQL staging password
SSL mode	Disable


Because pgAdmin and PostgreSQL are in the same Docker Compose network, pgAdmin must connect using:
db:5432

not:
127.0.0.1:5432

6. Operational Notes
- Staging uses its own PostgreSQL data directory and must not reuse the development database volume.
- POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB initialize only a new/empty PostgreSQL data directory.
- Changing those values later does not automatically update an existing database.
- Use:
docker compose down

for normal shutdown.
Avoid:
docker compose down -v

unless named-volume deletion is intentional.
Current scope does not include PostgreSQL TLS/SSL or monitoring integration. These can be added later without changing the core staging database setup.