# Builds Mentor from Windows by running build.sh inside an Arch Linux WSL2 distro.
#   .\build\build.ps1          -> out\mentor.qcow2 (for the launcher)
#   .\build\build.ps1 iso      -> out\mentor-*.iso
param(
    [ValidateSet('disk', 'iso')]
    [string]$Target = 'disk',
    [string]$Distro = 'archlinux'
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot

$env:WSL_UTF8 = '1'
$installed = @()
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    $installed = @(wsl.exe -l -q 2>$null) | ForEach-Object { ($_ -replace "`0", '').Trim() }
}
if ($installed -notcontains $Distro) {
    Write-Host "The WSL distro '$Distro' is not installed. In an administrator PowerShell run:"
    Write-Host "    wsl --install archlinux"
    Write-Host "Reboot if Windows asks for it, then run this script again."
    exit 1
}

$unix = $root -replace '\\', '/'
$unix = '/mnt/' + $unix.Substring(0, 1).ToLower() + $unix.Substring(2)

wsl.exe -d $Distro -u root -- bash "$unix/build/build.sh" $Target
exit $LASTEXITCODE
