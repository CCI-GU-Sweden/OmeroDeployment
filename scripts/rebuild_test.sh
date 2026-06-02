#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-core-omero-test}"

echo "WARNING: This will delete ALL OMERO test data and database state in namespace: ${NAMESPACE}"
read -p "Type yes to continue: " confirm

if [ "$confirm" != "yes" ]; then
echo "Aborted."
exit 1
fi

echo "Switching to project ${NAMESPACE}..."
oc project "${NAMESPACE}"

echo "Scaling down services..."
oc scale deployment omero-web --replicas=0
oc scale deployment flask-app --replicas=0
oc scale deployment dashboard-test --replicas=0
oc scale deployment omero-server --replicas=0
oc scale deployment omero-postgres-server --replicas=0

echo "Waiting for pods to terminate..."
sleep 20

echo "Deleting OMERO repository and database PVCs..."
oc delete pvc server-cap-omero omero-postgresql-pvc

echo "Waiting for PVC deletion..."
while oc get pvc server-cap-omero >/dev/null 2>&1; do
sleep 2
done

while oc get pvc omero-postgresql-pvc >/dev/null 2>&1; do
sleep 2
done

echo "Recreating PVCs and PostgreSQL..."
oc apply -f server/pvc-cap-omero.yaml
oc apply -f postgres/postgresql.yaml

echo "Waiting for PostgreSQL deployment..."
oc rollout status deployment/omero-postgres-server

echo "Starting OMERO server..."
oc apply -f server/server-deployment.yaml
oc scale deployment omero-server --replicas=1
oc rollout status deployment/omero-server

echo "Starting OMERO.web..."
oc apply -f web/web-deployment.yaml
oc scale deployment omero-web --replicas=1
oc rollout status deployment/omero-web

echo "Starting dependent applications..."
oc scale deployment flask-app --replicas=1
oc rollout status deployment/flask-app

oc scale deployment dashboard-test --replicas=1
oc rollout status deployment/dashboard-test

echo "OMERO test rebuild completed successfully."

