# Installs Mentor OS: downloads the setup program from the latest release and starts it.
#
#     irm https://raw.githubusercontent.com/Hnd-VXD/Mentor_OS/main/install.ps1 | iex
#
# It is the same MentorSetup.exe as on the release page. Fetched this way it does not carry
# Windows' "came from the internet" mark, so Windows does not stop to warn about a program it
# has not seen often yet. Read this file before running it: that is the point of it being short.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$setup = Join-Path $env:TEMP 'MentorSetup.exe'
Write-Host 'Downloading the Mentor setup program...'
Invoke-WebRequest 'https://github.com/Hnd-VXD/Mentor_OS/releases/latest/download/MentorSetup.exe' -OutFile $setup -UseBasicParsing
Write-Host "Starting it. Its SHA-256 is $((Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()); the release notes say what it should be."
Start-Process $setup
