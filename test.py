PostgreSQL and pgAdmin – Staging Setup
Overview
The NMDB staging environment uses PostgreSQL and pgAdmin deployed on a Rocky Linux VM using Docker Compose.
Current staging database configuration:
PostgreSQL Host : 10.192.24.81
PostgreSQL Port : 8080
Database        : nmdb_staging

pgAdmin         : http://10.192.24.81/

PostgreSQL runs inside the container on port 5432 and is exposed through host port 8080.
pgAdmin connects to PostgreSQL internally using:
Host : db
Port : 5432

The current PostgreSQL image is:
postgres:18.6-bookworm

Persistent PostgreSQL data is stored under:
/opt/postgres-staging/data

The staging database is used by release/stage/staging branches through Jenkins environment configuration.
Prerequisites
The staging VM requires:
Rocky Linux
Docker
Docker Compose
Access to the internal container registry
Required firewall ports opened

Required ports:
8080/tcp  - PostgreSQL
80/tcp    - pgAdmin

Create the PostgreSQL persistent directory:
sudo mkdir -p /opt/postgres-staging/data
sudo chown -R 999:999 /opt/postgres-staging/data

Docker Compose Configuration
The staging Compose file contains PostgreSQL and pgAdmin services.
Example structure:
services:
  db:
    image: postgres:18.6-bookworm
    container_name: nmdb-postgres-staging
    restart: unless-stopped

    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: nmdb_staging

    ports:
      - "8080:5432"

    volumes:
      - /opt/postgres-staging/data:/var/lib/postgresql:Z

  pgadmin:
    image: <pgadmin-image>
    container_name: nmdb-pgadmin-staging
    restart: unless-stopped

    environment:
      PGADMIN_DEFAULT_EMAIL: ${PGADMIN_DEFAULT_EMAIL}
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD}

    ports:
      - "80:80"

    depends_on:
      - db

Credentials should be maintained through an .env file or another approved secret/configuration mechanism and should not be committed into source control.
pgAdmin Connection
After pgAdmin is started, register the staging PostgreSQL server using:
Name        : NMDB Staging
Host        : db
Port        : 5432
Database    : nmdb_staging
Username    : <postgres user>
Password    : <postgres password>
SSL Mode    : Disable

Important:
External connection:
10.192.24.81:8080

pgAdmin internal connection:
db:5432

Jenkins Integration
The staging database values are maintained through Jenkins environment variables:
STAGE_DB_HOST=10.192.24.81
STAGE_DB_PORT=8080
STAGE_DB_NAME=nmdb_staging
STAGE_SCHEMA_PREFIX=stage_

Branches matching:
release/*
stage/*
staging/*

use the staging PostgreSQL instance.
Branch-specific schemas are created in the format:
stage_<branch_name>
stage_<branch_name>_nec

Database passwords remain stored in Jenkins Credentials.
Important Commands
Start or update the services:
docker compose up -d

Check status:
docker compose ps

View PostgreSQL logs:
docker compose logs db

View pgAdmin logs:
docker compose logs pgadmin

Restart services:
docker compose restart

Stop services:
docker compose down