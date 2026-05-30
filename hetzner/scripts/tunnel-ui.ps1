<#
.SYNOPSIS
  Open an SSH tunnel to the server-side Streamlit UI.

.DESCRIPTION
  Forwards localhost:<LocalPort> -> server 127.0.0.1:8501 (the loopback-published
  `ui` service in docker-compose.prod.yml). Leave this window open, then browse
  http://localhost:8501. Press Ctrl+C to close the tunnel.

.EXAMPLE
  ./tunnel-ui.ps1 -Server root@203.0.113.10
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,  # e.g. root@203.0.113.10
    [int]$LocalPort = 8501
)

Write-Host "Tunnel: http://localhost:$LocalPort -> $Server (Streamlit :8501). Ctrl+C to close." -ForegroundColor Cyan
ssh -N -L "${LocalPort}:localhost:8501" $Server
