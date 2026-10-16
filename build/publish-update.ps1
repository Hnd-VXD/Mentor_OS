# Makes a Mentor update from the source as it is now, signs it, and (with -Upload) publishes it on
# GitHub, where every Mentor looks once a day (distro/rootfs/etc/mentor/UPDATES.md).
#
#   .\build\publish-update.ps1 -Summary "One or two plain sentences: what is new or fixed."
#   .\build\publish-update.ps1 -Summary "..." -Upload
#
# The summary is what users read on the card that asks them, so it is written for them.
# The signing key stays on this computer ($HOME\.mentor\update-signing-key); every Mentor carries the
# public half (etc/mentor/update-signers) and installs nothing that it did not sign.
#   .\build\publish-update.ps1 -Summary "..." -Notes notes.md -Upload
#
# -Notes: the maker's notes for the assistant (build/update-notes-template.md says how to write them):
# what changed and why, and step by step what the files alone cannot do. Signed with the update.
param(
    [Parameter(Mandatory = $true)][string]$Summary,
    [string]$Notes = '',
    # The problem reports this update fixes (their issue numbers in Mentor_Reports), as "12,15": the Mentor
    # that sent one tells its user so on the update's card.
    [string]$Fixes = '',
    [switch]$Upload,
    [string]$Key = (Join-Path $HOME '.mentor\update-signing-key'),
    [string]$Repo = 'Hnd-VXD/Mentor_OS'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root 'out\update'
if (-not (Test-Path $Key)) { Write-Host "The signing key is missing: $Key"; exit 1 }
if ($Summary.Trim().Length -lt 10) { Write-Host 'Write a summary for the users: what is new or fixed.'; exit 1 }

# 1. The package: Mentor's own files exactly as an image gets them (build.sh update).
$env:WSL_UTF8 = '1'
$wslRoot = '/mnt/' + $root.Substring(0, 1).ToLower() + ($root.Substring(2) -replace '\\', '/')
wsl.exe -d archlinux -u root -- env "MENTOR_OUT=$wslRoot/out" bash "$wslRoot/build/build.sh" update
$built = $LASTEXITCODE
wsl.exe --shutdown  # WSL keeps the memory it used, which Mentor itself needs
if ($built -ne 0) { Write-Host 'The update could not be built.'; exit 1 }
$package = Get-ChildItem $out -Filter 'mentor-update-*.tar.zst' | Sort-Object LastWriteTime | Select-Object -Last 1
$version = [long]($package.BaseName -replace '^mentor-update-(\d+)\.tar$', '$1')

# 2. What it is, signed.
$sha = (Get-FileHash $package.FullName -Algorithm SHA256).Hash.ToLower()
$info = [ordered]@{ version = $version; summary = $Summary.Trim(); file = $package.Name; size = $package.Length;
                    sha256 = $sha; built = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm') + ' UTC' }
# The name people read (15.10.26.01), as build.sh gave it.
$nameFile = Join-Path $out 'version-name'
if (Test-Path $nameFile) { $info.name = (Get-Content $nameFile -Raw).Trim() }
if ($Fixes) { $info.fixes = @($Fixes -split '[,\s]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }) }
Get-ChildItem $out -Filter 'mentor-update-*.md' | Remove-Item
$notesFile = $null
if ($Notes) {
    if (-not (Test-Path $Notes)) { Write-Host "The notes are missing: $Notes"; exit 1 }
    $notesFile = Join-Path $out "mentor-update-$version.md"
    # As UTF-8 without a byte order mark and with Unix line ends, as Mentor reads it.
    $text = [IO.File]::ReadAllText((Resolve-Path $Notes)) -replace "`r`n", "`n"
    [IO.File]::WriteAllText($notesFile, $text, (New-Object Text.UTF8Encoding($false)))
    $info.notes = Split-Path -Leaf $notesFile
    $info.notes_size = (Get-Item $notesFile).Length
    $info.notes_sha256 = (Get-FileHash $notesFile -Algorithm SHA256).Hash.ToLower()
}
$json = Join-Path $out 'update.json'
[IO.File]::WriteAllText($json, ($info | ConvertTo-Json) + "`n", (New-Object Text.UTF8Encoding($false)))
Remove-Item "$json.sig" -ErrorAction SilentlyContinue
& ssh-keygen -q -Y sign -f $Key -n mentor-update $json
if ($LASTEXITCODE -ne 0) { Write-Host 'Signing failed.'; exit 1 }
# Checked the way Mentor checks it, with the public key the images carry.
$signers = Join-Path $root 'distro\rootfs\etc\mentor\update-signers'
# (through cmd: a PowerShell pipe would hand ssh-keygen the text re-encoded, not the file's bytes)
cmd /c "ssh-keygen -Y verify -f `"$signers`" -I mentor-update -n mentor-update -s `"$json.sig`" < `"$json`" > nul"
if ($LASTEXITCODE -ne 0) { Write-Host 'The signature does not match the key in the images.'; exit 1 }
Write-Host "Update $($info.name) ($version) is ready in $out ($([math]::Round($package.Length / 1MB, 1)) MB)."
if (-not $Upload) { Write-Host 'Not uploaded: run again with -Upload to publish it.'; exit 0 }

# 3. Publish: the release "updates" holds the newest package, update.json and its signature.
#    The package first, then the signature and update.json: until they arrive, Mentors see the old one.
& gh release view updates --repo $Repo *> $null
if ($LASTEXITCODE -ne 0) {
    & gh release create updates --repo $Repo --title 'Mentor updates' --latest=false `
        --notes 'Signed updates of Mentor''s own files. Mentor finds and installs them by itself, after asking; there is nothing to download here.'
    if ($LASTEXITCODE -ne 0) { Write-Host 'The release could not be made.'; exit 1 }
}
& gh release upload updates --repo $Repo --clobber $package.FullName
if ($LASTEXITCODE -ne 0) { Write-Host 'The package could not be uploaded.'; exit 1 }
if ($notesFile) {
    & gh release upload updates --repo $Repo --clobber $notesFile
    if ($LASTEXITCODE -ne 0) { Write-Host 'The notes could not be uploaded.'; exit 1 }
}
& gh release upload updates --repo $Repo --clobber "$json.sig" $json
if ($LASTEXITCODE -ne 0) { Write-Host 'update.json could not be uploaded.'; exit 1 }
# Older packages are of no use to anyone: update.json names only the newest.
$assets = & gh release view updates --repo $Repo --json assets --jq '.assets[].name'
foreach ($name in $assets) {
    $current = @($package.Name)
    if ($notesFile) { $current += (Split-Path -Leaf $notesFile) }
    if ($name -like 'mentor-update-*' -and $current -notcontains $name) { & gh release delete-asset updates $name --repo $Repo --yes }
}
# Remembered in the source: the next image says it has this update in it (build.sh, updates-included.json).
$listPath = Join-Path $root 'distro\updates.json'
$list = @()
# (through ForEach-Object: Windows PowerShell 5 hands a JSON list on as one item)
if (Test-Path $listPath) { $list = @(Get-Content $listPath -Raw | ConvertFrom-Json | ForEach-Object { $_ }) }
$record = [ordered]@{ version = $version; name = $info.name; summary = $info.summary;
                      published = (Get-Date).ToString('yyyy-MM-dd HH:mm') }
if ($info.fixes) { $record.fixes = $info.fixes }
$list += [pscustomobject]$record
[IO.File]::WriteAllText($listPath, (ConvertTo-Json -InputObject @($list) -Depth 3) + "`n", (New-Object Text.UTF8Encoding($false)))
if ($notesFile) {
    New-Item -ItemType Directory -Force (Join-Path $root 'distro\update-notes') | Out-Null
    Copy-Item $notesFile (Join-Path $root "distro\update-notes\$version.md")
}
Write-Host "Published update $($info.name) ($version). Every Mentor offers it within a day."
