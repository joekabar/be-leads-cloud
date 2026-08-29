<#
.SYNOPSIS
    Nightly chunked goudengids scrape. Driven by a Windows Scheduled Task.

.DESCRIPTION
    goudengids sits behind an Imperva WAF that blocks on sustained volume: a 103-sector
    run served 8 sectors in ~30 minutes, then blocked 15 of the next 21. Scraping a small
    slice per night keeps each session under that threshold.

    Asks be-leads-next-sectors which sectors still need work (a sector counts as done only
    if it produced observations; a blocked run is retried), then scrapes just those.
    Exits quietly when the city is fully covered.

    NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads a BOM-less UTF-8 script
    as ANSI, so a non-ASCII character inside a string breaks the parser.

    Exit codes -- the Scheduled Task's LastTaskResult is the only thing most people
    glance at, so a night that produced nothing must not report 0:
      0  scraped normally (a blocked sector is expected and stays queued)
      1  unhandled terminating error, or a non-zero exit from the batch
      3  database unavailable
      4  sectors failed outright, e.g. DNS or the browser never reached the site
      5  scraped fine, but a source failed, e.g. the Brave API returning HTTP 402
      6  data preflight failed (health check inside be-leads-nightly)

.EXAMPLE
    .\nightly_scrape.ps1 -City oostende -Limit 15
#>
[CmdletBinding()]
param(
    # Empty means "ask be-leads-next-city", which walks the rotation in
    # src/scraper/lib/scrape_cities.toml and finishes one city before starting the next.
    # Pass a slug to pin a single city.
    [string] $City   = '',
    [int]    $Limit  = 10,
    [string] $LogDir = '',
    # Run the database preflight and stop. Lets the dependency be verified without
    # spending an hour of WAF budget on a real scrape.
    [switch] $CheckOnly
)

$ErrorActionPreference = 'Stop'

# Do NOT use $PSScriptRoot in a param() default: under `powershell.exe -File` from Task
# Scheduler it can be empty, which sends output to the drive root instead of the repo.
# Exit code stays 0, so the failure is invisible. Resolve from $PSCommandPath instead.
$scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
$repo = Split-Path -Parent (Split-Path -Parent $scriptPath)
if (-not $LogDir) { $LogDir = Join-Path $repo 'logs' }
Set-Location $repo

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
$state = Join-Path $LogDir 'nightly_scrape.log'
# The run log is named after the city, which is not known until the rotation is queried,
# and that needs the database. Preflight output therefore goes to its own file.
$preflightLog = Join-Path $LogDir "preflight_${stamp}.log"
$log = $preflightLog

function Write-State([string] $msg) {
    "[$(Get-Date -Format s)] $msg" | Add-Content -Path $state -Encoding utf8
}

Write-State "START city=$(if ($City) { $City } else { '<rotation>' }) limit=$Limit"

# A night that produced nothing must still say so. Without this trap a terminating error
# leaves START as the last line in the log and the failure is invisible until someone
# notices the data has stopped moving -- which is exactly how the five days above passed.
trap {
    Write-State "END exit=1 reason=unhandled :: $($_.Exception.Message)"
    exit 1
}

# ---------------------------------------------------------------------------
# Database preflight.
#
# Every step below needs Postgres, which runs in Docker. Docker Desktop does not
# start at login on this host, so a reboot leaves the whole night dead: the
# 2026-07-30 session found the database down with nothing to say why. Bring it up
# here rather than discovering it three commands later.
# ---------------------------------------------------------------------------

function Test-DbPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', 5432)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-DockerDaemon {
    # stderr is noise here; only the exit code matters.
    & docker info --format '{{.ServerVersion}}' *> $null
    return ($LASTEXITCODE -eq 0)
}

function Wait-For([scriptblock] $Condition, [int] $TimeoutSeconds, [int] $IntervalSeconds = 5) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Seconds $IntervalSeconds
    }
    return $false
}

function Initialize-Database {
    if (Test-DbPort) {
        # Something is already listening. Any deeper problem will surface as a clear
        # error from the CLI that follows, which is a better message than a probe here.
        return $true
    }

    Write-State 'PREFLIGHT database unreachable on 127.0.0.1:5432, starting it'

    if (-not (Test-DockerDaemon)) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path $desktop)) {
            Write-State "PREFLIGHT FAILED Docker daemon is down and $desktop is missing"
            return $false
        }
        Write-State 'PREFLIGHT starting Docker Desktop'
        Start-Process $desktop
        if (-not (Wait-For { Test-DockerDaemon } 300 10)) {
            Write-State 'PREFLIGHT FAILED Docker daemon did not come up within 300s'
            return $false
        }
    }

    # Idempotent: a container that is already up is left alone.
    & docker compose up -d pg *>> $log
    if ($LASTEXITCODE -ne 0) {
        Write-State "PREFLIGHT FAILED docker compose up -d pg exit=$LASTEXITCODE"
        return $false
    }

    # An open port is not readiness: after a cold start Postgres binds 5432 while still
    # recovering and rejects connections for the better part of a minute.
    $ready = Wait-For {
        & docker compose exec -T pg pg_isready -U leads *> $null
        return ($LASTEXITCODE -eq 0)
    } 300 5

    if (-not $ready) {
        Write-State 'PREFLIGHT FAILED Postgres did not accept connections within 300s'
        return $false
    }

    Write-State 'PREFLIGHT database is up'
    return $true
}

$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $dbOk = Initialize-Database
} finally {
    $ErrorActionPreference = $prevEap
}

if (-not $dbOk) {
    Write-State 'END exit=3 reason=database-unavailable'
    Write-Output 'Database unavailable, nothing scraped. See the log.'
    exit 3
}

if ($CheckOnly) {
    Write-State 'END exit=0 reason=check-only'
    Write-Output 'Preflight OK: database reachable.'
    exit 0
}

# Everything from here down - city selection, sector queue, batch, verdict - lives in
# Python now (src/scraper/pipeline/nightly.py), where pytest reaches it. This script
# is OS glue: scheduling, Docker preflight, and relaying an exit code. The Python side
# appends to the same state log in the same format, so the history stays greppable.
$runLog = Join-Path $LogDir "nightly_run_${stamp}.log"

$argList = @('run', 'be-leads-nightly', '--limit', $Limit, '--state-log', $state)
if ($City) { $argList += @('--city', $City) }

$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & uv @argList *>> $runLog
    $code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
}

exit $code
