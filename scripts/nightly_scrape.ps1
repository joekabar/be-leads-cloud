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

.EXAMPLE
    .\nightly_scrape.ps1 -City oostende -Limit 15
#>
[CmdletBinding()]
param(
    [string] $City   = 'oostende',
    [int]    $Limit  = 15,
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
$log   = Join-Path $LogDir "nightly_scrape_${City}_${stamp}.log"
$state = Join-Path $LogDir 'nightly_scrape.log'

function Write-State([string] $msg) {
    "[$(Get-Date -Format s)] $msg" | Add-Content -Path $state -Encoding utf8
}

Write-State "START city=$City limit=$Limit"

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

# Which sectors still need work?
$raw = & uv run be-leads-next-sectors --city $City --limit $Limit 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-State "FAILED next-sectors exit=$LASTEXITCODE :: $raw"
    exit $LASTEXITCODE
}

$sectors = @($raw | Where-Object { $_ -and ("$_".Trim() -ne '') } | ForEach-Object { "$_".Trim() })

if ($sectors.Count -eq 0) {
    Write-State "DONE city=$City is fully covered, nothing to scrape tonight"
    Write-Output "Nothing to scrape: $City is fully covered."
    exit 0
}

$joined = $sectors -join ', '
Write-State "SCRAPE $($sectors.Count) sectors: $joined"

$argList = @('run', 'be-leads-pipeline-batch', '--city', $City)
foreach ($s in $sectors) { $argList += @('--sector', $s) }

# Staging is already loaded, so spend the night on discovery rather than re-emitting KBO.
$argList += @('--skip-kbo-dump')

# Windows PowerShell 5.1 wraps every stderr line from a native exe in a NativeCommandError
# record. Under $ErrorActionPreference = 'Stop' that record is terminating, so the script
# died here and never reached the summary below: the 2026-07-30 run logged START and SCRAPE,
# no END, and exited 1 after a batch that had in fact completed cleanly. structlog writes
# all logging to stderr, so this fired on every run, not on failures only. Drop to
# 'Continue' for the duration of the call and read the real exit code afterwards.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & uv @argList *>> $log
    $code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
}

$done    = @(Select-String -Path $log -Pattern 'goudengids_sector_done' -ErrorAction SilentlyContinue).Count
$blocked = @(Select-String -Path $log -Pattern 'goudengids_imperva_block' -ErrorAction SilentlyContinue).Count

Write-State "END exit=$code sectors_done=$done blocks=$blocked log=$log"
Write-Output "Scraped $done sectors, $blocked blocked. Log: $log"

if ($blocked -gt 0) {
    Write-State "NOTE $blocked sectors were blocked and remain queued for the next night"
}

exit $code
