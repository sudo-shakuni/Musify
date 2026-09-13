# Marko-Time 1-Click Windows Installer
# Usage: irm https://raw.githubusercontent.com/sudo-shakuni/marko-time/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
Write-Host "==================================================" -ForegroundColor Green
Write-Host "🎵 Installing Marko-Time v1.0.0 for Windows..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

$InstallDir = "$env:LOCALAPPDATA\Marko-Time"
$ZipUrl = "https://github.com/sudo-shakuni/marko-time/archive/refs/heads/main.zip"
$TempZip = "$env:TEMP\marko-time-main.zip"
$TempExtract = "$env:TEMP\Marko-Time-Extract"

Write-Host "📥 Downloading latest Marko-Time package from GitHub..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing

if (Test-Path $TempExtract) {
    Remove-Item -Path $TempExtract -Recurse -Force -ErrorAction SilentlyContinue
}
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
} else {
    Write-Host "🔄 Updating existing installation at $InstallDir..." -ForegroundColor Yellow
}

Write-Host "📦 Extracting files to $InstallDir..." -ForegroundColor Cyan
Copy-Item -Path "$TempExtract\marko-time-main\*" -Destination $InstallDir -Recurse -Force
Remove-Item -Path $TempExtract -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path $TempZip -Force -ErrorAction SilentlyContinue

# Setup Python Environment & Dependencies
Write-Host "🐍 Setting up Python environment and dependencies..." -ForegroundColor Cyan
$VenvPython = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in $InstallDir\.venv..." -ForegroundColor Yellow
    $PythonExe = "python"
    if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
        if (Get-Command "py" -ErrorAction SilentlyContinue) {
            $PythonExe = "py"
        } elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
            $PythonExe = "python3"
        } else {
            Write-Error "Python is not installed or not added to PATH. Please install Python 3."
        }
    }
    & $PythonExe -m venv "$InstallDir\.venv"
}

Write-Host "📦 Installing requirements..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install --quiet -r "$InstallDir\requirements.txt"

# Ensure FFmpeg is present
Write-Host "🎬 Verifying FFmpeg binaries..." -ForegroundColor Cyan
& $VenvPython "$InstallDir\setup_ffmpeg.py"

# Create Desktop Shortcut
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\marko-time.lnk")
$Shortcut.TargetPath = "$InstallDir\marko-time.bat"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Marko-Time — Studio-Grade Music & Playlist Downloader"
if (Test-Path "$InstallDir\frontend\logo.jpg") {
    $Shortcut.IconLocation = "$InstallDir\frontend\logo.jpg,0"
}
$Shortcut.Save()

Write-Host "✨ Installation Complete! Desktop shortcut created." -ForegroundColor Green
Write-Host "🚀 Launching Marko-Time..." -ForegroundColor Green

Start-Process -FilePath "$InstallDir\marko-time.bat" -WorkingDirectory $InstallDir
