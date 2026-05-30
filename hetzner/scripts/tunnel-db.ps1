<#
.SYNOPSIS
  Open an SSH tunnel from this laptop to the Hetzner Postgres.

.DESCRIPTION
  Forwards localhost:<LocalPort> -> server 127.0.0.1:5432 (the loopback-published
  Postgres in docker-compose.prod.yml). Leave this window open while you use the
  local UI; press Ctrl+C to close the tunnel.

.EXAMPLE
  ./tunnel-db.ps1 -Server root@203.0.113.10
  ./tunnel-db.ps1 -Server root@203.0.113.10 -LocalPort 5433
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,  # e.g. root@203.0.113.10
    [int]$LocalPort = 5433
)

Write-Host "Tunnel: localhost:$LocalPort -> $Server (Postgres :5432). Ctrl+C to close." -ForegroundColor Cyan
ssh -N -L "${LocalPort}:localhost:5432" $Server
