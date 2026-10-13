# Compiles MentorSetup.exe, the one file a new user downloads, into out\release.
param([string]$Out = '')
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { Write-Host "C# compiler not found: $csc"; exit 1 }
if (-not $Out) { $Out = Join-Path $root 'out\release\MentorSetup.exe' }
New-Item -ItemType Directory (Split-Path -Parent $Out) -Force | Out-Null

& $csc /nologo /target:winexe /optimize+ /platform:x64 `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    "/win32icon:$(Join-Path $PSScriptRoot 'Mentor.ico')" "/resource:$(Join-Path $PSScriptRoot 'emblem.png'),emblem.png" `
    "/out:$Out" (Join-Path $PSScriptRoot 'MentorSetup.cs')
exit $LASTEXITCODE
