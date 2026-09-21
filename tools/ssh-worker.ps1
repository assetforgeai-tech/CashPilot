[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $WorkerId,
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $ResourceGroup,
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $VmName,
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $KeyPath,
    [string] $Subscription,
    [string] $User = "cashpilot",
    [string] $Command = "hostname"
)

$ErrorActionPreference = "Stop"
$preflight = Join-Path $PSScriptRoot "azure-worker-preflight.ps1"
$preflightArgs = @("-WorkerId", $WorkerId, "-ResourceGroup", $ResourceGroup, "-VmName", $VmName)
if ($Subscription) { $preflightArgs += @("-Subscription", $Subscription) }
$preflightJson = & pwsh -NoProfile -NonInteractive -File $preflight @preflightArgs
if ($LASTEXITCODE -ne 0) { throw "Azure worker preflight failed; SSH was not attempted." }

try { $preflightResult = ($preflightJson -join "`n" | ConvertFrom-Json) }
catch { throw "Azure worker preflight returned invalid JSON: $($_.Exception.Message)" }
if (-not $preflightResult.port22) { throw "Azure worker preflight did not confirm TCP port 22." }

$resolvedKey = (Resolve-Path -LiteralPath $KeyPath -ErrorAction Stop).Path
$sshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=30",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "IdentitiesOnly=yes",
    "-i", $resolvedKey,
    "$User@$($preflightResult.publicIpAddress)",
    $Command
)
& ssh @sshArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
