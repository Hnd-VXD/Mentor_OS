# Compiles Mentor.exe into the project root with the C# compiler that ships with Windows.
param(
    [string]$Out = '',      # another place for the program, for trying a change out
    # The launcher's version, which its self-update compares (SelfUpdate.cs): the build time, UTC.
    [long]$Version = [long](Get-Date).ToUniversalTime().ToString('yyyyMMddHHmm'),
    # The key whose signature on launcher.json it trusts: the public half of Mentor's update key, as the
    # images carry it. Another one only for a test build.
    [string]$Signer = ''
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { Write-Host "C# compiler not found: $csc"; exit 1 }
if (-not $Signer) {
    $line = Get-Content (Join-Path $root 'distro\rootfs\etc\mentor\update-signers') | Where-Object { $_ -match 'ssh-ed25519' } | Select-Object -First 1
    $Signer = ($line -split '\s+')[-1]
}
if ($Signer -notmatch '^AAAAC3NzaC1lZDI1NTE5[A-Za-z0-9+/=]+$') { Write-Host "Not an Ed25519 public key: $Signer"; exit 1 }
$stamp = Join-Path ([IO.Path]::GetTempPath()) "mentor-launcher-build-$PID.cs"
Set-Content -Encoding ASCII $stamp @"
// Written by build-launcher.ps1 for each build.
static class LauncherBuild
{
    public const long Version = $Version;
    public const string Signer = "$Signer";
}
"@

# /target:winexe is what keeps a console window from opening.
$sources = 'Mentor.cs', 'Ui.cs', 'SelfUpdate.cs', 'Power.cs', 'TimeZone.cs', 'HostLink.cs', 'Devices.cs', 'Resources.cs',
    'LauncherWindow.cs', 'SettingsDialog.cs', 'Usb.cs', 'Hello.cs', 'Tray.cs', 'Diagnostics.cs', 'Backup.cs' |
    ForEach-Object { Join-Path $PSScriptRoot $_ }
& $csc /nologo /target:winexe /optimize+ /platform:x64 `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    /reference:System.Numerics.dll /reference:System.Management.dll /reference:System.IO.Compression.dll `
    /reference:System.IO.Compression.FileSystem.dll `
    "/win32icon:$(Join-Path $PSScriptRoot 'Mentor.ico')" "/resource:$(Join-Path $PSScriptRoot 'emblem.png'),emblem.png" `
    "/out:$(if ($Out) { $Out } else { Join-Path $root 'Mentor.exe' })" @sources $stamp
$built = $LASTEXITCODE
Remove-Item $stamp
exit $built
