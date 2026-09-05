$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceBase = Join-Path ([IO.Path]::GetTempPath()) ('earnapp-publish-' + [guid]::NewGuid().ToString('N'))
$remoteRoot = '/tmp/cashpilot-earnapp-generic-20260905'
$publishTag = if ($env:EARNAPP_PUBLISH_TAG) { $env:EARNAPP_PUBLISH_TAG } else { '20260905-gap2' }
$vpsFile = 'D:\1. WORK_true\CashPilot\earnapp_update_05092026\vps.txt'
$credential = @{}
Get-Content -LiteralPath $vpsFile | ForEach-Object {
    if ($_ -match '^\s*([^#:=]+?)\s*[:=]\s*(.*?)\s*$') {
        $credential[$matches[1].Trim().ToLowerInvariant()] = $matches[2].Trim()
    }
}
$ghcrToken = (Get-Content -LiteralPath 'D:\AI_System\ghcr\info.txt' -Raw).Trim()
$plink = 'C:\Program Files\PuTTY\plink.exe'
$pscp = 'C:\Program Files\PuTTY\pscp.exe'
$passwordFile = Join-Path ([IO.Path]::GetTempPath()) ('earnapp-vps-' + [guid]::NewGuid().ToString('N') + '.txt')
$tokenFile = Join-Path ([IO.Path]::GetTempPath()) ('earnapp-ghcr-' + [guid]::NewGuid().ToString('N') + '.txt')
[IO.File]::WriteAllText($passwordFile, $credential['password'], (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($tokenFile, $ghcrToken, (New-Object Text.UTF8Encoding($false)))
try {
    New-Item -ItemType Directory -Path $sourceBase | Out-Null
    foreach ($platform in @('macos', 'ios', 'ubuntu')) {
        $context = Join-Path $sourceBase $platform
        & python (Join-Path $repoRoot 'scripts/build_earnapp_canary_image.py') --platform $platform --context-dir $context | Out-Null
        tar -C $context -czf (Join-Path $sourceBase "$platform-context.tar.gz") .
    }
    & $plink -batch -ssh -l $credential['user'] -pwfile $passwordFile $credential['ip'] "rm -rf $remoteRoot; mkdir -p $remoteRoot" | Out-Null
    foreach ($platform in @('macos', 'ios', 'ubuntu')) {
        & $pscp -batch -pwfile $passwordFile (Join-Path $sourceBase "$platform-context.tar.gz") ($credential['user'] + '@' + $credential['ip'] + ":$remoteRoot/$platform-context.tar.gz") | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "upload failed: $platform" }
    }
    $remoteScript = @'
set -euo pipefail
ROOT=__REMOTE_ROOT__
for p in macos ios ubuntu; do
  rm -rf "$ROOT/$p"
  mkdir -p "$ROOT/$p"
  tar -xzf "$ROOT/$p-context.tar.gz" -C "$ROOT/$p"
done
sudo docker login ghcr.io -u assetforgeai-tech --password-stdin < "$ROOT/ghcr-token.txt" >/dev/null
for p in macos ios ubuntu; do
  tag=$p
  [[ "$p" == macos ]] && tag=mac-canary
sudo docker build --pull=false -t "cashpilot/earnapp-$tag:$publishTag" "$ROOT/$p"
done
sudo docker tag "cashpilot/earnapp-mac-canary:$publishTag" "ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos:$publishTag"
sudo docker tag "cashpilot/earnapp-ios:$publishTag" "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios:$publishTag"
sudo docker tag "cashpilot/earnapp-ubuntu:$publishTag" "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu:$publishTag"
sudo docker push "ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos:$publishTag"
sudo docker push "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios:$publishTag"
sudo docker push "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu:$publishTag"
sudo docker logout ghcr.io >/dev/null
sudo docker image inspect "ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos:$publishTag" "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios:$publishTag" "ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu:$publishTag" --format '{{.RepoTags}} {{.Id}}'
rm -f "$ROOT/ghcr-token.txt"
rm -rf "$ROOT"
'@
    $remoteScript = $remoteScript.Replace('__REMOTE_ROOT__', $remoteRoot).Replace('$publishTag', $publishTag)
    [IO.File]::WriteAllText((Join-Path $sourceBase 'remote.sh'), $remoteScript, (New-Object Text.UTF8Encoding($false)))
    & $pscp -batch -pwfile $passwordFile $tokenFile ($credential['user'] + '@' + $credential['ip'] + ":$remoteRoot/ghcr-token.txt") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'GHCR token upload failed' }
    & $pscp -batch -pwfile $passwordFile (Join-Path $sourceBase 'remote.sh') ($credential['user'] + '@' + $credential['ip'] + ":$remoteRoot.sh") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'remote script upload failed' }
    $output = & $plink -batch -ssh -l $credential['user'] -pwfile $passwordFile $credential['ip'] "bash $remoteRoot.sh" 2>&1
    $output | Tee-Object -FilePath (Join-Path $repoRoot 'docs/research/earnapp-generic-image-publish.txt')
    if ($LASTEXITCODE -ne 0) { throw 'generic image build or publish failed' }
}
finally {
    Remove-Item -LiteralPath $passwordFile, $tokenFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $sourceBase -Recurse -Force -ErrorAction SilentlyContinue
}
