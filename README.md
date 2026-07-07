# OmeroDeployment

Kubernetes/OpenShift manifests and build files for running an
[OMERO](https://www.openmicroscopy.org/omero/) deployment with supporting
services.

The repository is currently tailored for the CCI GU OpenShift environment, but
the manifests are plain YAML and can be adapted to another Kubernetes cluster by
changing storage classes, image references, secrets, ConfigMaps, Services, and
Routes/Ingresses.

## What is included

| Path | Purpose |
| --- | --- |
| `postgres/` | PostgreSQL deployment and backup CronJob manifests. |
| `server/` | OMERO.server Dockerfile, deployment, PVCs, startup/config files, root password file, and PVC migration helpers. |
| `web/` | OMERO.web deployment, PVCs, Django secret key/config files, and experimental OAuth test code. |
| `redis/` | Redis deployment used by supporting services. |
| `flask/` | Flask-based OMERO frontend/upload helper Dockerfile, deployment, config, and PVCs. |
| `filestatistics/` | File statistics PostgreSQL deployment and storage PVC. |
| `dashboard/` | Dashboard deployment plus notes for its required configuration. |
| `scripts/` | Operational helper scripts, including test-environment rebuild/reset tooling. |

## Prerequisites

- Access to a Kubernetes or OpenShift cluster.
- `kubectl` or `oc` configured for the target namespace/project.
- Storage classes matching the manifests, or edited manifests that use storage
  classes available in your cluster. Current examples include:
  - `block-standard`
  - `shared-standard`
  - `shared-economy`
- Access to the container registries referenced by the manifests.
- Built and pushed images for manifests that still contain project-specific
  image references or placeholders such as `IMAGE-URL`.
- Secrets and ConfigMaps created before applying deployments that reference
  them.

## Repository-specific configuration

Before deploying, review and adapt the manifests for your environment.

### Images

Several deployment files point to GU/OpenShift image registries, GitHub-built
application images, or placeholders:

- `dashboard/dashboard.yml` deploys the dashboard image. The application source
  is maintained separately in the dashboard GitHub repository.
- `flask/deploy-flask.yaml` deploys the Flask helper/frontend image. Build it
  from the Flask application source and push it to a registry your cluster can
  pull from.
- `server/server-deployment.yaml` currently contains `IMAGE-URL`. This should
  point to the OMERO.server image you want to run. The local `server/Dockerfile`
  builds from the public `openmicroscopy/omero-server:5.6` base image and adds
  extra Python dependencies.
- `web/web-deployment.yaml` currently points to
  `registry.k8s.gu.se/openshift/omero-web:2.4`. That is a prebuilt registry
  image reference. If the target cluster cannot pull from that registry, replace
  it with a public or locally built OMERO.web image.
- `postgres/postgresbackup.yaml` currently contains `IMAGE-URL`. Replace it
  with an image that contains the PostgreSQL client tools needed by the backup
  CronJob, such as `pg_dump`, plus `gzip` and shell utilities.

In short: the server and backup manifests use placeholders, the web manifest
uses a prebuilt registry image, and the dashboard/Flask manifests deploy images
that are built separately from their source projects. Any image can be shared if
it is pushed to a registry that the target cluster can access; private
GU/OpenShift registry references will not be portable outside that environment.

The included build contexts are:

```sh
docker build -t <registry>/<namespace>/omero-server:<tag> server
docker build -t <registry>/<namespace>/omero-frontend:<tag> flask
```

Push the images and update the corresponding `image:` fields in the manifests.

### Required secrets

The main PostgreSQL and OMERO.server manifests expect these secrets:

```sh
oc create secret generic postgresql-secret \
  --from-literal=POSTGRESQL_DATABASE=omerodb \
  --from-literal=POSTGRESQL_USER=omero \
  --from-literal=POSTGRESQL_PASSWORD='<database-password>' \
  --from-literal=POSTGRESQL_ADMIN_PASSWORD='<admin-password>'

oc create secret generic omero-server-root-password \
  --from-literal=password='<omero-root-password>'

oc create secret generic django-secret-key \
  --from-file=django_secret_key=web/django_secret_key
```

Use `kubectl` instead of `oc` if you are not on OpenShift.

### Required ConfigMaps

The OMERO.server deployment mounts local configuration files as ConfigMaps:

```sh
oc create configmap 60-db-cf --from-file=60-database.sh=server/60-database.sh
oc create configmap 01-gu-config --from-file=01-gu-config.omero=server/01-gu-config.omero
oc create configmap server-figure-to-pdf --from-file=Figure_To_Pdf.py=server/Figure_To_Pdf.py
oc create configmap logback.xml --from-file=logback.xml=server/logback.xml
```

The OMERO.web deployment expects:

```sh
oc create configmap omeroweb-config.omero --from-file=omeroweb-config.omero=web/omeroweb-config.omero
oc create configmap 50-config.py --from-file=50-config.py=web/50-config.py
```

It also references `oauth-providers.yaml`. Create that ConfigMap if OAuth is
enabled in your deployment:

```sh
oc create configmap oauth-providers.yaml --from-file=oauth-providers.yaml=<path-to-oauth-providers.yaml>
```

The Flask deployment expects:

```sh
oc create configmap config.py --from-file=config.py=flask/config.py
oc create configmap local-uwsgi.ini --from-file=local-uwsgi.ini=<path-to-local-uwsgi.ini>
```

The dashboard deployment expects a `dashboard-db-config` ConfigMap containing:

```text
API_TOKEN
JWT_SECRET
PGDATABASE
PGHOST
PGPASSWORD
PGPORT
PGUSER
```

See `dashboard/README.md` for the current dashboard-specific notes.

## Suggested deployment order

Apply resources in dependency order. For OpenShift:

```sh
oc project <project-name>

# 1. Create Secrets and ConfigMaps first.

# 2. Storage.
oc apply -f postgres/postgresql.yaml
oc apply -f server/pvc-omero.yaml
oc apply -f server/pvc-cap-omero.yaml
oc apply -f server/pvc-opt-omero.yaml
oc apply -f web/pvc-omero-web.yaml
oc apply -f web/pvc-opt-omero-web.yaml
oc apply -f flask/flask-upload.yaml
oc apply -f flask/flask-logs.yaml
oc apply -f flask/flask-slash-omero.yaml
oc apply -f flask/flask-slash-cache.yaml
oc apply -f filestatistics/filestatistics-storage.yml

# 3. Databases and cache.
oc apply -f filestatistics/filestatisticsdb.yml
oc apply -f redis/redis-omero.yml

# 4. OMERO services and supporting applications.
oc apply -f server/server-deployment.yaml
oc apply -f web/web-deployment.yaml
oc apply -f flask/deploy-flask.yaml
oc apply -f dashboard/dashboard.yml
```

Then verify rollout status:

```sh
oc rollout status deployment/omero-postgres-server
oc rollout status deployment/omero-server
oc rollout status deployment/omero-web
oc rollout status deployment/flask-app
```

## Services and external access

This repository does not currently include a complete set of Service,
Route, or Ingress manifests for every application.

The PostgreSQL manifest includes an internal service named
`omero-postgres-server`. OMERO.server uses that service through
`CONFIG_omero_db_host`.

Create additional Services and OpenShift Routes or Kubernetes Ingresses for the
applications that should be reachable by users, for example:

- OMERO.web on container port `4080`
- OMERO.server ports `4063` and `4064`
- Flask app on the port exposed by its container image
- Dashboard if used

## Notes and caveats

- `postgres/postgresql.yaml` contains an inline init SQL example with a sample
  database password. Prefer creating real credentials through Kubernetes Secrets
  and avoid committing production passwords.
- `postgres/postgresbackup.yaml` is namespace- and image-specific. Update
  `metadata.namespace`, the PostgreSQL service host, secret names, PVC name, and
  backup image before using it.
- `web/web-deployment.yaml` currently references PVC claim names
  `opt-omero-web` and `omero-web`; the PVC files define `web-opt-omero-web` and
  `web-omero-web`. Align those names before deploying OMERO.web.
- `flask/deploy-flask.yaml` is environment-specific and should be validated
  after editing images and ConfigMaps.
- `server/server-deployment.yaml` initializes OMERO data into mounted PVCs using
  an init container. Be careful when reusing existing PVCs.

## Operations

### Rebuilding a test environment

`scripts/rebuild_test.sh` is an OpenShift helper script for resetting a test
namespace. It scales services down, deletes selected OMERO/database PVCs,
reapplies manifests, and scales services back up.

It is destructive. Read the script and confirm the namespace before running:

```sh
scripts/rebuild_test.sh <namespace>
```

### PVC migration

`server/migrate_pvc_data/` contains helper manifests for copying data between
PVCs. The copy pod mounts an original and a new PVC so data can be copied from
inside the pod.

Review and edit the `claimName` values in
`server/migrate_pvc_data/copy_pvc_data.yaml` before applying it.

### Backups

`postgres/postgresbackup.yaml` defines a CronJob-style PostgreSQL backup
example. Before using it, ensure that:

- the backup PVC exists,
- the referenced PostgreSQL secret exists,
- the PostgreSQL host and database values match your deployment,
- the backup image contains `pg_dump`, `gzip`, and shell utilities,
- the namespace is correct.

## License

This repository is licensed under the terms in `LICENSE`.
