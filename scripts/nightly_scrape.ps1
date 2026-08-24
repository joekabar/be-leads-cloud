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

# Run a `uv` command, capture its stdout, and survive whatever it writes to stderr.
#
# Two separate hazards, both of which cost real nights:
#
# 1. Windows PowerShell 5.1 wraps every stderr line from a native exe in a
#    NativeCommandError record. Under $ErrorActionPreference = 'Stop' that record is
#    TERMINATING, so the script dies mid-statement -- before the `if ($LASTEXITCODE...)`
#    below it can log anything. uv writes ordinary progress to stderr ("Uninstalled 1
#    package in 0.3ms"), so this fired on perfectly healthy runs. Between 2026-08-12 and
#    2026-08-17 every scheduled run logged START, nothing else, and exited 1: ten dead
#    nights, no error, five days of stale data.
# 2. Capturing with `2>&1` merges those stderr lines into the returned value. Even with
#    the crash fixed, the caller would then treat "Uninstalled 1 package" as a city name.
#
# So: drop to 'Continue' for the duration of the call, send stderr to a log instead of
# into the value, and hand back the real exit code.
function Invoke-Uv {
    param(
        [Parameter(Mandatory)] [string[]] $Arguments,
        [Parameter(Mandatory)] [string]   $ErrLog
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $all  = & uv @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }

    # 2>&1 merges the streams, but the objects stay distinguishable: stderr arrives as an
    # ErrorRecord, stdout as a plain string. Splitting on type keeps "Uninstalled 1 package"
    # out of the returned value while still preserving it for diagnosis. Note the stderr is
    # written with Add-Content -Encoding utf8 rather than a bare `2>>` redirection, which in
    # PowerShell 5.1 emits UTF-16 and would corrupt a log the rest of this script wrote UTF-8.
    $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
    if ($err.Count) {
        $err | ForEach-Object { "[$(Get-Date -Format s)] stderr: $_" } |
            Add-Content -Path $ErrLog -Encoding utf8
    }

    return [PSCustomObject]@{
        ExitCode = $code
        Output   = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] })
    }
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

# Which city is the rotation on? Finishes one city before starting the next; prints
# nothing once every configured city is complete.
if (-not $City) {
    $nextCity = Invoke-Uv -Arguments @('run', 'be-leads-next-city') -ErrLog $log
    if ($nextCity.ExitCode -ne 0) {
        Write-State "FAILED next-city exit=$($nextCity.ExitCode) see=$log"
        exit $nextCity.ExitCode
    }
    $City = @($nextCity.Output | Where-Object { $_ -and ("$_".Trim() -ne '') } |
        ForEach-Object { "$_".Trim() }) | Select-Object -First 1

    if (-not $City) {
        Write-State 'END exit=0 reason=all-cities-complete'
        Write-Output 'Nothing to scrape: every configured city is complete.'
        exit 0
    }
    Write-State "CITY $City (from rotation)"
}

# Now the city is known, so the run log can be named after it.
$log = Join-Path $LogDir "nightly_scrape_${City}_${stamp}.log"

# Which sectors still need work?
$nextSectors = Invoke-Uv -Arguments @('run', 'be-leads-next-sectors', '--city', $City, '--limit', $Limit) -ErrLog $log
if ($nextSectors.ExitCode -ne 0) {
    Write-State "FAILED next-sectors exit=$($nextSectors.ExitCode) see=$log"
    exit $nextSectors.ExitCode
}

$sectors = @($nextSectors.Output | Where-Object { $_ -and ("$_".Trim() -ne '') } | ForEach-Object { "$_".Trim() })

if ($sectors.Count -eq 0) {
    Write-State "DONE city=$City is fully covered, nothing to scrape tonight"
    Write-Output "Nothing to scrape: $City is fully covered."
    exit 0
}

$joined = $sectors -join ', '
Write-State "SCRAPE $($sectors.Count) sectors: $joined"

$summaryFile = Join-Path $LogDir "batch_summary_${City}_${stamp}.json"

$argList = @('run', 'be-leads-pipeline-batch', '--city', $City)
foreach ($s in $sectors) { $argList += @('--sector', $s) }

# Staging is already loaded, so spend the night on discovery rather than re-emitting KBO.
$argList += @('--skip-kbo-dump')

# The batch already knows exactly how the night went. Have it say so in a file rather
# than making this script infer it from the log -- see the summary handling below.
$argList += @('--summary-json', $summaryFile)

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

# How the night actually went.
#
# This used to be decided by grepping the log for 'goudengids_sector_done', which counts
# sectors ATTEMPTED, not sectors that produced anything. On 2026-08-22 and 2026-08-23 a
# DNS failure (ERR_NAME_NOT_RESOLVED) made all ten sectors fail in each of four
# consecutive runs, and every one of them logged 'END exit=0 sectors_done=0 blocks=0' --
# indistinguishable from 'nothing left to scrape'. Two days, zero observations, no alarm.
# The same grep reported sectors_done=10 for a run the batch itself scored as 6.
#
# So read the batch's own summary. Fall back to the old grep only if the file is missing,
# which means the batch died before writing it -- itself worth reporting.
$blocked = @(Select-String -Path $log -Pattern 'goudengids_imperva_block' -ErrorAction SilentlyContinue).Count
$sectorFailures = @(Select-String -Path $log -Pattern 'goudengids_sector_failed' -ErrorAction SilentlyContinue).Count

$scraped   = $null
$attempted = $sectors.Count
$failedSources = @()

if (Test-Path $summaryFile) {
    try {
        $summary = Get-Content -Path $summaryFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $scraped   = [int] $summary.goudengids_sectors_scraped
        $attempted = [int] $summary.sectors
        if ($summary.sources_failed) {
            $failedSources = @($summary.sources_failed.PSObject.Properties |
                ForEach-Object { "$($_.Name)=$($_.Value)" })
        }
    } catch {
        Write-State "NOTE could not read $summaryFile :: $($_.Exception.Message)"
    }
} else {
    Write-State "NOTE batch wrote no summary file, falling back to log counting"
}

if ($null -eq $scraped) {
    $scraped = @(Select-String -Path $log -Pattern 'goudengids_sector_done' -ErrorAction SilentlyContinue).Count
}

# A sector that finished but inserted nothing is normal -- everything it found was
# already seen inside the dedup window. A sector that FAILED is not. Blocks are counted
# and reported separately; they leave the sector queued and are expected on this host.
$reason = ''
if ($code -ne 0) {
    $reason = 'batch-exit'
} elseif ($sectorFailures -gt 0) {
    $code = 4
    $firstError = (Select-String -Path $log -Pattern 'goudengids_sector_failed' -ErrorAction SilentlyContinue |
        Select-Object -First 1).Line
    if ($firstError -match "error='([^']{0,160})") { $reason = "sector-failures :: $($Matches[1])" }
    else { $reason = 'sector-failures' }
} elseif ($failedSources.Count -gt 0) {
    $code = 5
    $reason = "source-failed :: $($failedSources -join ', ')"
}

$suffix = if ($reason) { " reason=$reason" } else { '' }
Write-State "END exit=$code scraped=$scraped/$attempted failed=$sectorFailures blocks=$blocked log=$log$suffix"
Write-Output "Scraped $scraped of $attempted sectors, $sectorFailures failed, $blocked blocked. Log: $log"

if ($blocked -gt 0) {
    Write-State "NOTE $blocked sectors were blocked and remain queued for the next night"
}
foreach ($f in $failedSources) {
    Write-State "NOTE source failed: $f"
}

exit $code
