[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $ResourceGroup,
    [Parameter(Mandatory)] [string] $Name,
    [Parameter(Mandatory)] [string] $Region,
    [string] $VmSize = 'Standard_B2s',
    [string] $Image = 'Ubuntu2204',
    [ValidateRange(30, 4095)] [int] $OsDiskSizeGb = 64,
    [ValidateRange(1, 32)] [int] $PublicIpCount = 1,
    [string] $StartupScript = 'azure_create/worker-startup.sh',
    [string] $SshPublicKey,
    [string] $AdminUsername = 'cashpilot',
    [string] $AdminPassword,
    [string[]] $AllowedPorts = @('22'),
    [switch] $DryRun,
    [switch] $Verify
)

$ErrorActionPreference = 'Stop'
if ($AdminPassword) { Write-Warning 'Password mode is provided for Azure CLI compatibility; SSH key mode remains the default.' }
if (-not $SshPublicKey -and -not $AdminPassword) { throw 'Provide -SshPublicKey or opt in to -AdminPassword.' }
if ($AllowedPorts -contains '1-65535') { throw 'Full TCP+UDP requires explicit per-task approval and evidence.' }
if (-not (Test-Path -LiteralPath $StartupScript)) { throw "Startup script not found: $StartupScript" }

$args = @('vm', 'create', '--subscription', $SubscriptionId, '--resource-group', $ResourceGroup,
    '--name', $Name, '--location', $Region, '--size', $VmSize, '--image', $Image,
    '--os-disk-size-gb', $OsDiskSizeGb, '--public-ip-sku', 'Standard', '--nsg-rule', 'NONE',
    '--tags', 'cashpilot=true', "startup-script=$StartupScript", "public-ip-count=$PublicIpCount")
foreach ($port in $AllowedPorts) { $args += @('--nsg-rule', $port) }
if ($SshPublicKey) { $args += @('--admin-username', $AdminUsername, '--ssh-key-values', $SshPublicKey) }
if ($AdminPassword) { $args += @('--admin-username', $AdminUsername, '--admin-password', $AdminPassword) }

$payload = [ordered]@{ command = @('az') + $args; verify = @('az', 'vm', 'show', '--subscription', $SubscriptionId, '--resource-group', $ResourceGroup, '--name', $Name, '--show-details', '--output', 'json') }
if ($DryRun) { $payload | ConvertTo-Json -Compress; exit 0 }
& az @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Verify) { & az vm show --subscription $SubscriptionId --resource-group $ResourceGroup --name $Name --show-details --output json; exit $LASTEXITCODE }
