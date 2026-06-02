#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-core-omero-test}"

echo "This deletes all OMERO test data and DB state in namespace: ${NAMESPACE}"
read -p "Type yes to continue: " confirm

if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

oc project "$NAMESPACE"

echo "Scaling down dependent services..."
oc scale deployment omero-web --replicas=0
oc scale deployment flask-app --replicas=0
oc scale deployment dashboard-test --replicas=0
oc scale deployment omero-server --replicas=0
oc scale deployment omero-postgres-server --replicas=0

echo "Deleting OMERO test data PVCs..."
oc delete pvc server-cap-omero omero-postgresql-pvc

echo "Recreating PVCs and Postgres..."
oc apply -f server/pvc-cap-omero.yaml
oc apply -f postgres/postgresql.yaml

echo "Waiting for Postgres..."
oc rollout status deployment/omero-postgres-server

echo "Recreating/restarting OMERO server..."
oc apply -f server/server-deployment.yaml
oc scale deployment omero-server --replicas=1
oc rollout status deployment/omero-server

echo "Recreating/restarting OMERO.web..."
oc apply -f web/web-deployment.yaml
oc scale deployment omero-web --replicas=1
oc rollout status deployment/omero-web

echo "Restarting dependent apps..."
oc scale deployment flask-app --replicas=1
oc rollout status deployment/flask-app

oc scale deployment dashboard-test --replicas=1
oc rollout status deployment/dashboard-test

echo "Done. OMERO test rebuild completed."
