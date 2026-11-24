# Dashboard deployments

`dashboard.yml` and the legacy configuration below describe the older
dashboard. The current Django dashboard, its database migrations, image,
Secrets, approval endpoint and deployment instructions are maintained in
[Dashboard-django](https://github.com/CCI-GU-Sweden/Dashboard-django). Do not
apply `dashboard.yml` as a replacement for the Django deployment.

The optional ORCID integration crosses both repositories. See
[web/orcid/README.md](../web/orcid/README.md) for deployment order and the
dependencies that must be present before enabling ORCID on OMERO.web.

`orcid-dashboard-6f6756c.patch` is a frozen recovery snapshot of the tested
Django changes against Dashboard-django commit
`6f6756c2bafa9d9d0b90ed3ddc75447bb0458df4`. It is not an independently
maintained Django release. Review and integrate it into the dashboard source
before building a reproducible image; see the ORCID runbook for recovery steps.

## Legacy dashboard configuration

The legacy deployment expects `dashboard-db-config` keys `API_TOKEN`,
`JWT_SECRET`, `PGDATABASE`, `PGHOST`, `PGPASSWORD`, `PGPORT` and `PGUSER`.
These keys are not the Django dashboard configuration. Treat their values as
credentials and store them in a suitable Secret rather than committing them.
