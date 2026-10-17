# Makes a new Mentor.exe from launcher/ as it is now, signs what it is, and (with -Upload) publishes it
# in the GitHub release "updates", where every Mentor.exe from 2026-10-18 on looks for a newer one of
# itself when it starts (launcher/SelfUpdate.cs).
#
#   .\build\publish-launcher.ps1 -Summary "One plain sentence: what is new."
#   .\build\publish-launcher.ps1 -Summary "..." -Upload
#
# The signing key stays on this computer ($HOME\.mentor\update-signing-key), the same one as for the
# image's updates (publish-update.ps1), under its own namespace "mentor-launcher". Every Mentor.exe
# carries the public half (build-launcher.ps1 takes it from distro/rootfs/etc/mentor/update-signers).
#
# Without -Upload nothing leaves this computer: the files are in out\launcher\ for testing, e.g. with
# a local server: python -m http.server 8766 --directory out\launcher (started with PowerShell's
# Start-Process), and a test Mentor.exe built with an older -Version, named Mentor.exe in a folder of its
# own, started with MENTOR_LAUNCHER_UPDATES=http://127.0.0.1:8766/. How it swaps and goes back:
# launcher/SelfUpdate.cs; what users see: distro/rootfs/etc/mentor/WINDOWS.md, section 1.
#
# Every Mentor.exe before the self-update (up to a1f005ce…, 2026-10-17) still needs MentorSetup.exe run
# again once to get one that has it.
#
# The release "latest" keeps its own Mentor.exe for MentorSetup.exe; a fresh installation updates
# itself to this one at its first start.
param(
    [Parameter(Mandatory = $true)][string]$Summary,
    [switch]$Upload,
    [string]$Key = (Join-Path $HOME '.mentor\update-signing-key'),
    [string]$Repo = 'Hnd-VXD/Mentor_OS'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root 'out\launcher'
if (-not (Test-Path $Key)) { Write-Host "The signing key is missing: $Key"; exit 1 }
if ($Summary.Trim().Length -lt 10) { Write-Host 'Write a summary: what is new or fixed.'; exit 1 }
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem $out -Filter 'Mentor-*.exe' | Remove-Item
Remove-Item (Join-Path $out 'launcher.json*') -ErrorAction SilentlyContinue

# 1. The program, with its version built in.
$version = [long](Get-Date).ToUniversalTime().ToString('yyyyMMddHHmm')
$name = "Mentor-$version.exe"
$program = Join-Path $out $name
& (Join-Path $root 'launcher\build-launcher.ps1') -Out $program -Version $version
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $program)) { Write-Host 'Mentor.exe could not be built.'; exit 1 }

# 2. What it is, signed.
$file = Get-Item $program
$info = [ordered]@{ version = $version; file = $name; size = $file.Length
                    sha256 = (Get-FileHash $program -Algorithm SHA256).Hash.ToLower(); summary = $Summary.Trim()
                    built = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm') + ' UTC' }
$json = Join-Path $out 'launcher.json'
[IO.File]::WriteAllText($json, ($info | ConvertTo-Json) + "`n", (New-Object Text.UTF8Encoding($false)))
& ssh-keygen -q -Y sign -f $Key -n mentor-launcher $json
if ($LASTEXITCODE -ne 0) { Write-Host 'Signing failed.'; exit 1 }

# 3. Checked twice: by OpenSSH against the key the images carry, and by the new program itself, which
#    is how every Mentor.exe will check it.
$line = Get-Content (Join-Path $root 'distro\rootfs\etc\mentor\update-signers') | Where-Object { $_ -match 'ssh-ed25519' } | Select-Object -First 1
$signers = Join-Path $out 'signers'
[IO.File]::WriteAllText($signers, ($line -replace 'namespaces="[^"]*"', 'namespaces="mentor-launcher"') + "`n")
cmd /c "ssh-keygen -Y verify -f `"$signers`" -I mentor-update -n mentor-launcher -s `"$json.sig`" < `"$json`" > nul"
$openssh = $LASTEXITCODE
Remove-Item $signers
if ($openssh -ne 0) { Write-Host 'The signature does not match the key in the images.'; exit 1 }
$check = Start-Process -FilePath $program -ArgumentList '--check-signature', "`"$json`"", "`"$json.sig`"", 'mentor-launcher' -Wait -PassThru
if ($check.ExitCode -ne 0) { Write-Host 'The new Mentor.exe does not accept its own signature.'; exit 1 }
Write-Host "Mentor.exe $version is ready in $out ($([math]::Round($file.Length / 1KB)) KB)."
if (-not $Upload) { Write-Host 'Not uploaded: run again with -Upload to publish it.'; exit 0 }

# 4. Publish: the program first, then the signature and launcher.json. Until they arrive, every
#    Mentor.exe still sees the one before.
& gh release view updates --repo $Repo *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'The release "updates" is missing (publish-update.ps1 makes it).'; exit 1 }
& gh release upload updates --repo $Repo --clobber $program
if ($LASTEXITCODE -ne 0) { Write-Host 'The program could not be uploaded.'; exit 1 }
& gh release upload updates --repo $Repo --clobber "$json.sig" $json
if ($LASTEXITCODE -ne 0) { Write-Host 'launcher.json could not be uploaded.'; exit 1 }
$assets = & gh release view updates --repo $Repo --json assets --jq '.assets[].name'
foreach ($asset in $assets) {
    if ($asset -like 'Mentor-*.exe' -and $asset -ne $name) { & gh release delete-asset updates $asset --repo $Repo --yes }
}
# Remembered in the source, beside the image's updates.
$listPath = Join-Path $root 'distro\launcher-updates.json'
$list = @()
if (Test-Path $listPath) { $list = @(Get-Content $listPath -Raw | ConvertFrom-Json | ForEach-Object { $_ }) }
$list += [pscustomobject][ordered]@{ version = $version; sha256 = $info.sha256; summary = $info.summary
                                     published = (Get-Date).ToString('yyyy-MM-dd HH:mm') }
[IO.File]::WriteAllText($listPath, (ConvertTo-Json -InputObject @($list) -Depth 3) + "`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "Published Mentor.exe $version. Every Mentor.exe with the self-update takes it at its next start or the one after."
