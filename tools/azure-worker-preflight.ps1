[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $WorkerId,
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $ResourceGroup,
    [Parameter(Mandatory)] [ValidateNotNullOrEmpty()] [string] $VmName,
    [string] $Subscription
)

$ErrorActionPreference = "Stop"

function Invoke-AzureJson {
    param([string[]] $Arguments)
    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed (exit $LASTEXITCODE): $($output -join ' ')"
    }
    try { return ($output -join "`n" | ConvertFrom-Json) }
    catch { throw "Azure CLI returned invalid JSON: $($_.Exception.Message)" }
}

$scope = @("--resource-group", $ResourceGroup, "--name", $VmName)
if ($Subscription) { $scope += @("--subscription", $Subscription) }

$vm = Invoke-AzureJson (@("vm", "show", "--show-details") + $scope + @("--query", "{powerState:powerState}", "--output", "json"))
$powerState = [string]$vm.powerState
if ($powerState -ne "VM running") {
    throw "Worker '$WorkerId' VM '$VmName' is not running (PowerState/running: '$powerState')."
}

$ipResult = Invoke-AzureJson (@("vm", "list-ip-addresses") + $scope + @("--query", "[0].virtualMachine.network.publicIpAddresses[0].ipAddress", "--output", "json"))
$publicIp = [string]$ipResult
if ([string]::IsNullOrWhiteSpace($publicIp) -or $publicIp -eq "null") {
    throw "Worker '$WorkerId' VM '$VmName' has no public IP address."
}

$portOpen = Test-NetConnection -ComputerName $publicIp -Port 22 -InformationLevel Quiet
if (-not $portOpen) {
    throw "Worker '$WorkerId' public IP '$publicIp' is not reachable on TCP port 22."
}

[ordered]@{
    workerId = $WorkerId
    resourceGroup = $ResourceGroup
    vmName = $VmName
    powerState = $powerState
    publicIpAddress = $publicIp
    port22 = $true
} | ConvertTo-Json -Compress
