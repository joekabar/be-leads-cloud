<#
.SYNOPSIS
  Launch the Streamlit UI locally, pointed at the remote Postgres via the DB tunnel.

.DESCRIPTION
  Use this for the goudengids-local workflow: your laptop's residential IP can
  reach goudengids (the Hetzner datacenter IP is Imperva-blocked), and writes land
  in the same remote DB.

  Prerequisite: a DB tunnel is already open in another window
  (./tunnel-db.ps1 -Server user@HETZNER_IP), so localhost:<DbPort> reaches the
  remote Postgres.

  Then, in the UI sidebar, deselect every source except Goudengids (and optionally
  Company websites) and click Run pipeline.

.EXAMPLE
  $env:LEADS_PG_PASSWORD = "the-prod-password"
  ./run-ui-local.ps1 -Server-User leads
#>
param(
    [int]$DbPort = 5433,
    [string]$PgUser = "leads",          # must match POSTGRES_USER in hetzner/.env
    [string]$PgDb = "leads",            # must match POSTGRES_DB in hetzner/.env
    [string]$PgPassword = $env:LEADS_PG_PASSWORD
)

if (-not $PgPassword) {
    throw "Set the prod Postgres password: `$env:LEADS_PG_PASSWORD = '...'`  (or pass -PgPassword)."
}

$env:DATABASE_URL = "postgresql://${PgUser}:${PgPassword}@localhost:${DbPort}/${PgDb}"
Write-Host "DATABASE_URL -> localhost:$DbPort (remote DB via tunnel). Starting Streamlit..." -ForegroundColor Cyan

# Run from the repo root regardless of where this script is invoked.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot
try {
    uv run streamlit run src/scraper/ui/app.py
}
finally {
    Pop-Location
}
