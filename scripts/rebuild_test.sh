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

echo "Suspending cleanup CronJobs..."
oc patch cronjob omero-orphan-cleanup -p '{"spec":{"suspend":true}}' || true
oc patch cronjob cleanup-omero-test-uploads -p '{"spec":{"suspend":true}}' || true

echo "Scaling down services..."
oc scale deployment omero-web --replicas=0 || true
oc scale deployment flask-app --replicas=0 || true
oc scale deployment dashboard-test --replicas=0 || true
oc scale deployment omero-server --replicas=0 || true
oc scale deployment omero-postgres-server --replicas=0 || true

echo "Waiting for pods to terminate..."
sleep 30

echo "Deleting old cleanup pods that may hold PVCs..."
oc delete pod -l job-name --ignore-not-found=true || true

echo "Deleting OMERO repository, server opt, and database PVCs..."
oc delete pvc server-cap-omero server-opt-omero omero-postgresql-pvc --ignore-not-found=true

echo "Waiting for PVC deletion..."
for pvc in server-cap-omero server-opt-omero omero-postgresql-pvc; do
    while oc get pvc "$pvc" >/dev/null 2>&1; do
        sleep 2
    done
done

echo "Applying config and PVC/deployment manifests..."
oc apply -f server/pvc-cap-omero.yaml
oc apply -f server/pvc-opt-omero.yaml
oc apply -f postgres/postgresql.yaml
oc apply -f server/server-deployment.yaml
oc apply -f web/web-deployment.yaml

echo "Ensuring OMERO.web service points to classic OMERO.web port 4080..."
oc patch svc omero-web -p '{"spec":{"ports":[{"name":"4080-tcp","port":4080,"protocol":"TCP","targetPort":4080}]}}'

echo "Starting PostgreSQL..."
oc scale deployment omero-postgres-server --replicas=1
oc rollout status deployment/omero-postgres-server

echo "Starting OMERO server..."
oc scale deployment omero-server --replicas=1
oc rollout status deployment/omero-server

echo "Starting OMERO.web..."
oc scale deployment omero-web --replicas=1
oc rollout status deployment/omero-web

echo "Starting dependent applications..."
oc scale deployment flask-app --replicas=1
oc rollout status deployment/flask-app

oc scale deployment dashboard-test --replicas=1
oc rollout status deployment/dashboard-test

echo "Re-enabling cleanup CronJobs..."
oc patch cronjob omero-orphan-cleanup -p '{"spec":{"suspend":false}}' || true
oc patch cronjob cleanup-omero-test-uploads -p '{"spec":{"suspend":false}}' || true

echo "OMERO test rebuild completed successfully."
