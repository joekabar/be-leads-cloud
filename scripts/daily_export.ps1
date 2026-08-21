<#
.SYNOPSIS
    Daily lead export, one CSV per city. Intended to be driven by a Windows Scheduled Task.

.DESCRIPTION
    Writes a date-stamped CSV per city into -OutDir, then prunes exports older than
    -KeepDays.

    With no -City argument the script asks the database which cities the scraper has
    actually worked and writes a file for each. It used to default to a single pinned
    city, which meant it stood still while the rotation moved past it: when the rotation
    reached brugge on 2026-08-21 the scheduled task kept exporting oostende, and 2,170
    exportable brugge leads reached no file at all. Pass -City to override.

    Filters reproduce the micro-business brief: has a phone, and no published revenue
    above the ceiling. Companies with no revenue on file are KEPT -- micro enterprises
    file abbreviated accounts and publish no turnover, so excluding them would discard
    most of the list.

    NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads a BOM-less UTF-8 script
    as ANSI, so a non-ASCII character inside a string breaks the parser.

.EXAMPLE
    .\daily_export.ps1
    .\daily_export.ps1 -City oostende,brugge -MaxRevenue 2000000
#>
[CmdletBinding()]
param(
    # Empty means "ask the database which cities have been scraped".
    [string[]] $City         = @(),
    [string[]] $RequireField = @('phone'),
    [double]   $MaxRevenue   = 2000000,
    [string]   $OutDir       = '',
    [int]      $KeepDays     = 30
)

$ErrorActionPreference = 'Stop'

# Do NOT use $PSScriptRoot in a param() default: under `powershell.exe -File` from Task
# Scheduler it can be empty, which made $OutDir "\..\exports" and silently wrote every
# scheduled export to C:\exports instead of the repo's exports\ folder. Exit code was 0,
# so the failure was invisible. Resolve from $PSCommandPath in the body instead.
$scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
$repo = Split-Path -Parent (Split-Path -Parent $scriptPath)
if (-not $OutDir) { $OutDir = Join-Path $repo 'exports' }
Set-Location $repo

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp   = Get-Date -Format 'yyyy-MM-dd'
$logFile = Join-Path $OutDir 'daily_export.log'

function Write-Log([string] $msg) {
    "[$(Get-Date -Format s)] $msg" | Add-Content -Path $logFile -Encoding utf8
}

# Run a `uv` command, capture its stdout, and survive whatever it writes to stderr.
#
# Windows PowerShell 5.1 wraps every stderr line from a native exe in a NativeCommandError
# record, which is TERMINATING under $ErrorActionPreference = 'Stop'. uv writes ordinary
# progress to stderr, so `2>&1` here turned "Uninstalled 1 package in 0.3ms" into a fatal
# error: every four-hourly export from 2026-08-12 onwards logged `ERROR Uninstalled 1
# package` and wrote no CSV. Drop to 'Continue' for the call and read the real exit code
# afterwards.
#
# The two streams stay distinguishable after `2>&1` -- stderr arrives as an ErrorRecord,
# stdout as a plain string -- so splitting on type keeps uv's chatter out of the returned
# value while still logging it. Add-Content keeps the log UTF-8; a bare `2>>` would write
# UTF-16 into a file the rest of this script writes as UTF-8.
function Invoke-Uv {
    param([Parameter(Mandatory)] [string[]] $Arguments)

    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $all  = & uv @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }

    $out = @()
    foreach ($line in $all) {
        if ($line -is [System.Management.Automation.ErrorRecord]) {
            Write-Log "stderr: $line"
        } else {
            $out += "$line"
        }
    }

    return [PSCustomObject]@{ ExitCode = $code; Output = $out }
}

# A run that produced nothing must still say so. Without this trap a terminating error
# leaves START as the last line in the log and the failure is invisible until someone
# notices the exports have stopped moving.
trap {
    Write-Log "END exit=1 reason=unhandled :: $($_.Exception.Message)"
    exit 1
}

if ($City.Count -eq 0) {
    Write-Log 'START discovering cities'
    $discovered = Invoke-Uv -Arguments @('run', 'be-leads-export-cities')
    if ($discovered.ExitCode -ne 0) {
        Write-Log "END exit=$($discovered.ExitCode) reason=city-discovery-failed"
        exit $discovered.ExitCode
    }
    $City = @($discovered.Output | Where-Object { $_ -and ($_.Trim() -ne '') } |
        ForEach-Object { $_.Trim() })

    if ($City.Count -eq 0) {
        Write-Log 'END exit=0 reason=no-city-has-been-scraped-yet'
        Write-Output 'Nothing to export: no city has been scraped yet.'
        exit 0
    }
}

Write-Log "START cities=$($City -join ',') require=$($RequireField -join ',') max_revenue=$MaxRevenue"

$failed = 0
$total  = 0

foreach ($c in $City) {
    $outFile = Join-Path $OutDir "leads_${c}_${stamp}.csv"

    $argList = @('run', 'be-leads-export', '--out', $outFile, '--city', $c)
    foreach ($f in $RequireField) { $argList += @('--require-field', $f) }
    if ($MaxRevenue -gt 0)        { $argList += @('--max-revenue', $MaxRevenue) }

    $result = Invoke-Uv -Arguments $argList
    if ($result.ExitCode -ne 0) {
        Write-Log "FAILED city=$c exit=$($result.ExitCode)"
        $failed++
        continue
    }

    # Take the count from the CLI's own summary rather than counting lines in the file.
    # `(Get-Content | Measure-Object -Line).Lines - 1` counts PHYSICAL lines, and one
    # oostende address contains an embedded newline, so it reported 1977 rows for a
    # 1976-row file. The CLI counts records.
    $rows = 0
    foreach ($line in $result.Output) {
        if ($line -match 'Exported\s+(\d+)\s+rows') { $rows = [int]$Matches[1] }
    }
    $total += $rows
    Write-Log "OK city=$c $rows rows -> $outFile"
    Write-Output "Exported $rows rows to $outFile"
}

Write-Log "END exit=$(if ($failed) { 1 } else { 0 }) cities=$($City.Count) failed=$failed rows=$total"

# Prune old exports so the folder does not grow without bound.
if ($KeepDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem -Path $OutDir -Filter 'leads_*.csv' |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            Write-Log "PRUNE $($_.Name)"
            Remove-Item $_.FullName -Force
        }
}

if ($failed) { exit 1 }
