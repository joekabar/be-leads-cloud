<#
.SYNOPSIS
    Daily lead export. Intended to be driven by a Windows Scheduled Task.

.DESCRIPTION
    Writes a date-stamped CSV of companies matching the lead criteria into -OutDir,
    then prunes exports older than -KeepDays.

    Defaults reproduce the Oostende micro-business brief: in the city, has a phone,
    and no published revenue above the ceiling. Companies with no revenue on file are
    KEPT -- micro enterprises file abbreviated accounts and publish no turnover, so
    excluding them would discard most of the list.

.EXAMPLE
    .\daily_export.ps1 -City oostende -MaxRevenue 2000000
#>
[CmdletBinding()]
param(
    [string[]] $City       = @('oostende'),
    [string[]] $RequireField = @('phone'),
    [double]   $MaxRevenue = 2000000,
    [string]   $OutDir     = '',
    [int]      $KeepDays   = 30
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
$cityTag = ($City -join '-')
$outFile = Join-Path $OutDir "leads_${cityTag}_${stamp}.csv"
$logFile = Join-Path $OutDir 'daily_export.log'

$argList = @('run', 'be-leads-export', '--out', $outFile)
foreach ($c in $City)          { $argList += @('--city', $c) }
foreach ($f in $RequireField)  { $argList += @('--require-field', $f) }
if ($MaxRevenue -gt 0)         { $argList += @('--max-revenue', $MaxRevenue) }

"[$(Get-Date -Format s)] START uv $($argList -join ' ')" | Add-Content -Path $logFile -Encoding utf8

try {
    # Windows PowerShell 5.1 wraps every stderr line from a native exe in a
    # NativeCommandError record, which is TERMINATING under $ErrorActionPreference =
    # 'Stop'. uv writes ordinary progress to stderr, so `2>&1` here turned "Uninstalled 1
    # package in 0.3ms" into a fatal error: every four-hourly export from 2026-08-12
    # onwards logged `ERROR Uninstalled 1 package` and wrote no CSV. Drop to 'Continue'
    # for the call and read the real exit code afterwards. The row count below comes from
    # the CSV, not from $output, so mixed streams are safe to log verbatim here.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & uv @argList 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    # Both streams are logged, but they are tagged so a real failure is distinguishable from
    # uv's routine chatter. Add-Content keeps this UTF-8; a bare `2>>` would write UTF-16.
    $output | ForEach-Object {
        $tag = if ($_ -is [System.Management.Automation.ErrorRecord]) { 'stderr: ' } else { '' }
        "[$(Get-Date -Format s)] $tag$_"
    } | Add-Content -Path $logFile -Encoding utf8

    if ($code -ne 0) {
        "[$(Get-Date -Format s)] FAILED exit=$code" | Add-Content -Path $logFile -Encoding utf8
        exit $code
    }

    $rows = 0
    if (Test-Path $outFile) {
        # Subtract the header line.
        $rows = [Math]::Max(0, (Get-Content $outFile | Measure-Object -Line).Lines - 1)
    }
    "[$(Get-Date -Format s)] OK $rows rows -> $outFile" | Add-Content -Path $logFile -Encoding utf8
    Write-Output "Exported $rows rows to $outFile"
}
catch {
    "[$(Get-Date -Format s)] ERROR $($_.Exception.Message)" | Add-Content -Path $logFile -Encoding utf8
    throw
}

# Prune old exports so the folder does not grow without bound.
if ($KeepDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem -Path $OutDir -Filter 'leads_*.csv' |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            "[$(Get-Date -Format s)] PRUNE $($_.Name)" | Add-Content -Path $logFile -Encoding utf8
            Remove-Item $_.FullName -Force
        }
}
