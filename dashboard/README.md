To setup the dashboard, it will require the following ConfigMap details:

  API_TOKEN:
  JWT_SECRET:
  PGDATABASE: omerofilestats
  PGHOST: filestatisticsdb
  PGPASSWORD:
  PGPORT: '5432'
  PGUSER:

The API token is the password to access the database.
The JWT secret is to monitor the session with a token. Default is 1 hour long.

See the dashboard github for more details: https://github.com/CCI-GU-Sweden/Dashboard
