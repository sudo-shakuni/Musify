# Musify 1-Click Windows Installer
# Usage: irm https://raw.githubusercontent.com/sudo-shakuni/Musify/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
Write-Host "==================================================" -ForegroundColor Green
Write-Host "🎵 Installing Musify v1.0.0 for Windows..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

$InstallDir = "$env:LOCALAPPDATA\Musify"
$ZipUrl = "https://github.com/sudo-shakuni/Musify/releases/download/v1.0.0/Musify-v1.0.0-Windows.zip"
$TempZip = "$env:TEMP\Musify-v1.0.0-Windows.zip"

Write-Host "📥 Downloading Musify package from GitHub..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing

if (Test-Path $InstallDir) {
    Write-Host "🔄 Updating existing installation at $InstallDir..." -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

Write-Host "📦 Extracting files..." -ForegroundColor Cyan
Expand-Archive -Path $TempZip -DestinationPath $InstallDir -Force
Remove-Item -Path $TempZip -Force -ErrorAction SilentlyContinue

# Create Desktop Shortcut
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\Musify.lnk")
$Shortcut.TargetPath = "$InstallDir\Musify.bat"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Musify — Studio-Grade Music & Playlist Downloader"
if (Test-Path "$InstallDir\frontend\logo.jpg") {
    $Shortcut.IconLocation = "$InstallDir\frontend\logo.jpg,0"
}
$Shortcut.Save()

Write-Host "✨ Installation Complete! Desktop shortcut created." -ForegroundColor Green
Write-Host "🚀 Launching Musify..." -ForegroundColor Green

Start-Process -FilePath "$InstallDir\Musify.bat" -WorkingDirectory $InstallDir
