# My-Music 1-Click Windows Installer
# Usage: irm https://raw.githubusercontent.com/sudo-shakuni/my-music/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
Write-Host "==================================================" -ForegroundColor Green
Write-Host "🎵 Installing My-Music v1.0.0 for Windows..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

$InstallDir = "$env:LOCALAPPDATA\My-Music"
$ZipUrl = "https://github.com/sudo-shakuni/my-music/archive/refs/heads/main.zip"
$TempZip = "$env:TEMP\my-music-main.zip"
$TempExtract = "$env:TEMP\My-Music-Extract"

Write-Host "📥 Downloading latest My-Music package from GitHub..." -ForegroundColor Cyan
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
Copy-Item -Path "$TempExtract\my-music-main\*" -Destination $InstallDir -Recurse -Force
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
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\my-music.lnk")
$Shortcut.TargetPath = "$InstallDir\my-music.bat"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "My-Music — Studio-Grade Music & Playlist Downloader"
if (Test-Path "$InstallDir\frontend\logo.jpg") {
    $Shortcut.IconLocation = "$InstallDir\frontend\logo.jpg,0"
}
$Shortcut.Save()

Write-Host "✨ Installation Complete! Desktop shortcut created." -ForegroundColor Green
Write-Host "🚀 Launching My-Music..." -ForegroundColor Green

Start-Process -FilePath "$InstallDir\my-music.bat" -WorkingDirectory $InstallDir
