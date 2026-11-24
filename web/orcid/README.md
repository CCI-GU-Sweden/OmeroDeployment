# ORCID access for OMERO.web and OMERO_GU

This is the **test-validated** integration for the CCI Django dashboard and
OMERO. It is not automatically installed by `web/web-deployment.yaml`. It uses
real production ORCID authentication, including in `core-omero-test`; it does
not require ORCID sandbox accounts. Production deployment remains future work.
The base GU ADFS/2FA login remains available.

## How it works

1. A researcher signs in to the Django dashboard with ORCID. A CCI admin meets
   and verifies the researcher, then uses **Administration → External OMERO
   users** to link an existing OMERO account or request a new non-admin account
   in an approved existing OMERO group. Approval has a review/expiry date.
2. The researcher chooses ORCID in OMERO.web. `cci_orcid.py` verifies OAuth
   state, exchanges the authorization code with ORCID, and asks the dashboard
   approval API for the authenticated ORCID iD. It checks the mapped OMERO
   numeric user ID, username, active state and non-admin status before creating
   a session. A missing, expired, revoked or unavailable approval fails closed.
   No automatic username-based account creation occurs in this callback.
3. OMERO.server still enforces that account's group membership and permissions.
   For OMERO_GU, the researcher requests an OMERO session token through
   `/oauth/sessiontoken` and enters it in the upload app from an allowed
   microscope computer. The ORCID-issued upload session is registered too.
4. Revoking a link prevents new sessions. The worker checks for revoked,
   expired or disabled links every 30 seconds and closes tracked OMERO sessions;
   it retries failures. It stores numeric OMERO session IDs in the dashboard,
   not bearer UUIDs. GU sessions are not included. Actual closure can take
   longer when a component is unavailable; ORCID sessions have an eight-hour
   maximum lifetime. Administrator OMERO accounts are rejected by the ORCID
   callback so this path does not bypass GU's privileged 2FA.

New-account requests are claimed once. The worker creates the non-admin OMERO
user with no password and the chosen group, then records the link. A failed or
interrupted request may have created an account before communication failed;
it is not retried automatically. An administrator must inspect OMERO and the
request status and reconcile it. Never claim an existing username automatically.

## Components and source ownership

| Component | Location and responsibility |
| --- | --- |
| Dashboard | [Dashboard-django](https://github.com/CCI-GU-Sweden/Dashboard-django): authenticated identities, approval and provisioning UI, audit events, session tracking, approval API and database migrations. |
| OMERO.web callback | `cci_orcid.py` and `urls.py` here: guarded callback and tracked token issuance. The existing OMERO.oauth package provides GU login and OMERO connections. |
| OMERO worker | `cci_worker.py` here: polls the dashboard, closes revoked sessions and provisions requested OMERO accounts. It runs in the OMERO.web pod with access to the existing OMERO.oauth administrative connection. |
| Internal TLS | `approval-transport.yaml`: OpenShift service-serving certificate, CA bundle and proxy configuration. A dashboard sidecar terminates TLS and forwards only the approval endpoint to the dashboard on localhost. |
| OMERO_GU | [Omero_GU](https://github.com/CCI-GU-Sweden/Omero_GU): existing upload app and its existing microscope-only network restriction. |

The dashboard's implementation and the OMERO files must be released together.
At the time of this documentation, the tested Django implementation was an
**uncommitted local change and binary test build**, not a public release. A
frozen recovery snapshot is provided at
[`dashboard/orcid-dashboard-6f6756c.patch`](../../dashboard/orcid-dashboard-6f6756c.patch),
against Dashboard-django commit `6f6756c2bafa9d9d0b90ed3ddc75447bb0458df4`.
It includes the integration code, migrations `accounts.0008`–`0010` and tests;
it does not include credentials or an image. To recover, check out that exact
dashboard base in a clean, isolated checkout, run `git apply --check` on the
snapshot, then apply and review it. If the dashboard has advanced, reconcile
the changes manually rather than forcing the patch. Before a production rollout,
review and commit the integration in Dashboard-django and build an immutable
image from the reviewed revision. The snapshot is a fallback, not a substitute
for a maintained release. The test image digest and validation record are in
the dashboard repository's `deploy/openshift/ORCID-OMERO-TEST.md`. Preserve the
matching OMERO code in this directory and synchronize duplicated copies until
a single release process is established.

## Before deployment

- Identify the target namespace, OMERO.web hostname and server, dashboard
  hostname, network restrictions, service ownership and compatible image
  digests. The examples assume the dashboard and OMERO.web share a namespace;
  separate namespaces require secure token distribution, a certificate valid
  for the actual service name and reviewed network policies.
- Register the exact HTTPS OMERO callback
  `https://<omero-web-host>/oauth/callback/orcid` with a **production** ORCID
  client. The dashboard has its own registered callback. Obtain credentials
  through the approved secret-management process; do not put them in Git,
  command history, logs or chat. See [ORCID authentication documentation](https://info.orcid.org/documentation/api-tutorials/api-tutorial-get-and-authenticated-orcid-id/).
- Preserve the existing ADFS provider and its tested callback. Use a full
  provider configuration stored in an OpenShift Secret. The fragment
  `orcid-provider.yaml.example` is not a complete configuration. The deployed
  OMERO.oauth implementation needs an administrative OMERO connection; test
  currently uses `root`. Treat that credential as high impact, restrict its
  storage and access, and review whether a restricted administrator can safely
  perform all required operations. The old base examples may place credentials
  in ConfigMaps: replace that arrangement with an approved Secret-backed
  configuration before production; do not assume simply copying the old
  ConfigMap is secure.
- Back up and verify the dashboard PostgreSQL database and OMERO data. Confirm
  the migration role, runtime database grants, backup-reader grants and restore
  procedure. Restore the Django database, signing key and approved mappings
  together when recovering an existing installation. On a genuinely new
  installation, no users are approved until a CCI admin verifies them.
- Verify network isolation, HTTPS, proxy header trust and admin access. The
  dashboard's `DJANGO_TRUST_PROXY_HTTPS` must be enabled only when the proxy
  strips and sets the forwarded header. The approval sidecar sends the fixed
  `Host: dashboard-probe.local` and `X-Forwarded-Proto: https` to localhost;
  ensure that host is allowed and untrusted clients cannot spoof that proxy
  path. Use secure cookies and preserve the OMERO_GU microscope restriction.

## Rebuild from zero or deploy to a new environment

Use the normal repository deployment order for PostgreSQL, OMERO.server,
OMERO.web, Redis and OMERO_GU, adapting PVC names, routes and images. Deploy the
**current Django dashboard** from its own repository, not `dashboard.yml`.
Keep ORCID **disabled in the OMERO provider list** until the guarded callback
and worker are installed and tested.

1. Restore or create the dashboard database and credentials. Build the reviewed
   dashboard revision, take/verify backups, run its migrations once using the
   same immutable image digest, then grant the runtime role the required table
   and sequence privileges. Check migration plans and backup coverage. Deploy
   the matching dashboard image with its normal ORCID configuration and verify
   login, administrator access and its approval page.
2. Create an independent high-entropy Secret named
   `dashboard-omero-approval-token` with key `token` in the shared namespace;
   mount that **same Secret** into the dashboard and OMERO containers using
   `secretKeyRef`. Do not reuse the ORCID client secret or expose the token in
   command arguments. Give `OMERO_APPROVAL_SERVER` a stable environment-specific
   OMERO server identifier and `OMERO_APPROVAL_TOKEN` the token Secret key.
3. Review and apply `approval-transport.yaml` to the intended namespace. Verify
   that OpenShift created `dashboard-omero-approval-tls` and injected
   `dashboard-omero-approval-ca`. Adapt the dashboard selector and proxy host
   if needed. Merge a reviewed version of `dashboard-sidecar.patch.yaml.example`
   into the Django deployment, pin its TLS-capable proxy image, and verify a
   certificate-checked connection and rejection of unauthenticated requests.
   This path is internal and must not be exposed as a public unauthenticated API.
4. Create ConfigMap `dashboard-omero-orcid-code` from the reviewed source files:

   ```sh
   oc -n <namespace> create configmap dashboard-omero-orcid-code \
     --from-file=cci_orcid.py=web/orcid/cci_orcid.py \
     --from-file=urls.py=web/orcid/urls.py \
     --from-file=cci_worker.py=web/orcid/cci_worker.py
   ```

   Find the **installed** `omero_oauth` package used by the running OMERO.web
   process, not merely the source checkout. In the tested image it was under
   `/opt/omero/web/venv3/lib64/python3.9/site-packages/omero_oauth-0.1.0-py3.9.egg/omero_oauth`;
   this is image/version-specific. Inspect with the runtime Python from a neutral
   working directory and verify the actual served route. Review and merge
   `omero-web.patch.yaml.example`, replacing every placeholder and adapting PVC
   and config mounts to the deployment. The worker needs the same OMERO config,
   Python environment, token and trusted CA. ConfigMap `subPath` updates do not
   reach running containers: roll out the pod after every code change. PVCs
   populated with `cp -rn` can retain old packages after an image update; verify
   the active installed package and callback again on every upgrade.
5. With ORCID still absent from the provider list, verify that the live
   `/oauth/callback/orcid` is routed to the guarded code and rejects missing or
   invalid state, the worker is running and can reach the approval API, and GU
   login still works. Verify the administrative session-creation and closure
   privileges against the deployed OMERO version. Never enable ORCID on the
   upstream unmodified callback: it can automatically create active users.
6. In an approved secret store, merge `orcid-provider.yaml.example` into the
   full existing ADFS provider file with the environment's registered callback
   and credentials. Create a Secret containing key `oauth-providers.yaml` and
   switch only the `oauth-providers` volume to that Secret. Review the live
   volume first; do not apply an index-based JSON patch without a `test` for the
   volume name. Roll out OMERO.web and verify both provider buttons, the ORCID
   redirect host/callback, and GU login. Never print the Secret or include its
   contents in Git.
7. Run a pilot with a CCI-verified real ORCID user and a non-admin OMERO user in
   an explicitly approved test group. Verify dashboard access, OMERO.web identity
   and group permissions, OMERO_GU sign-in and a disposable upload. Test an
   unapproved identity, an expired/revoked link, a conflicting existing username,
   inactive and admin OMERO users, and unavailable dashboard/worker behavior.
   With disposable sessions, confirm revocation closes both ORCID-issued web and
   upload sessions while an unrelated GU session remains open. Check the queue,
   audit entries, backups and worker logs without printing session tokens.

For a new-account test, choose an existing non-system group. Verify the
worker-created user is active, non-admin, belongs only to the approved groups,
and is linked to the authenticated ORCID. Confirm failure or interruption is
visible and does not silently adopt an existing username. Retire synthetic test
accounts and retain relevant audit records according to local policy.

## Operation, recovery and rollback

Monitor `cci-orcid-revocation`, dashboard readiness, session-closure backlog,
pending/processing/failed provisioning requests, certificate expiry and backup
jobs. If the worker stops, existing ORCID sessions may remain active until it
recovers or their maximum lifetime expires. Do not promise immediate
revocation. A `processing` request can represent an account created before a
failed response; inspect OMERO and the dashboard audit before manual recovery.

To disable the feature, remove ORCID from the provider Secret and roll out
OMERO.web while preserving ADFS. Block new ORCID sessions and close/resolve
tracked active sessions before removing the worker. Revert the callback mounts,
worker and dashboard sidecar only after confirming no pending work. The
additive dashboard tables and recorded links must be preserved; do not reverse
migrations or restore an older database over later writes without a recovery
plan. Keep the previous image digest and reviewed configuration available.

Test evidence from `core-omero-test`: a real ORCID login and OMERO_GU image
upload succeeded; both sessions were tracked. A synthetic administrator-driven
revocation closed the selected test session and preserved a control session. A
synthetic provisioning request created a non-admin user in Metrology and was
then retired. These tests do not establish production readiness; review root
credential scope, monitoring, retention, recovery, expected revocation delay,
and GU/CCI policy before a production deployment.
