# Compiles Mentor.exe into the project root with the C# compiler that ships with Windows.
param([string]$Out = '')  # another place for the program, for trying a change out
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { Write-Host "C# compiler not found: $csc"; exit 1 }

# /target:winexe is what keeps a console window from opening.
& $csc /nologo /target:winexe /optimize+ /platform:x64 `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    "/win32icon:$(Join-Path $PSScriptRoot 'Mentor.ico')" "/resource:$(Join-Path $PSScriptRoot 'emblem.png'),emblem.png" `
    "/out:$(if ($Out) { $Out } else { Join-Path $root 'Mentor.exe' })" (Join-Path $PSScriptRoot 'Mentor.cs') (Join-Path $PSScriptRoot 'Ui.cs')
exit $LASTEXITCODE
