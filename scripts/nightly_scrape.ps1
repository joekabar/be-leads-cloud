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
    [string] $LogDir = ''
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

& uv @argList *>> $log
$code = $LASTEXITCODE

$done    = @(Select-String -Path $log -Pattern 'goudengids_sector_done' -ErrorAction SilentlyContinue).Count
$blocked = @(Select-String -Path $log -Pattern 'goudengids_imperva_block' -ErrorAction SilentlyContinue).Count

Write-State "END exit=$code sectors_done=$done blocks=$blocked log=$log"
Write-Output "Scraped $done sectors, $blocked blocked. Log: $log"

if ($blocked -gt 0) {
    Write-State "NOTE $blocked sectors were blocked and remain queued for the next night"
}

exit $code
