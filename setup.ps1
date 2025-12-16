# UV Project Auto-Setup and Runner Script
# This script checks for dependencies, installs them if missing, and sets up the piperun tool

# Set error action preference
$ErrorActionPreference = "Stop"

# Tool name variable - change this to rename the tool everywhere
$ToolName = "piperun"

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "$ToolName Auto-Setup" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Function to check if a command exists
function Test-CommandExists {
    param($Command)
    try {
        if (Get-Command $Command -ErrorAction Stop) {
            return $true
        }
    }
    catch {
        return $false
    }
}

# Function to check Python version
function Get-PythonVersion {
    try {
        $version = python --version 2>&1
        if ($version -match "Python (\d+\.\d+\.\d+)") {
            return $matches[1]
        }
    }
    catch {
        return $null
    }
}

# Check if cli.py exists
Write-Host "[1/5] Verifying project files..." -ForegroundColor Yellow
if (-not (Test-Path "cli.py")) {
    Write-Host "ERROR: 'cli.py' not found in current directory." -ForegroundColor Red
    Write-Host "Please run this script from the $ToolName project directory." -ForegroundColor Yellow
    exit 1
}
Write-Host "OK cli.py found" -ForegroundColor Green
Write-Host ""

# Check for Python
Write-Host "[2/5] Checking for Python..." -ForegroundColor Yellow
if (Test-CommandExists "python") {
    $pythonVersion = Get-PythonVersion
    Write-Host "OK Python is installed (version $pythonVersion)" -ForegroundColor Green
}
else {
    Write-Host "X Python is not installed" -ForegroundColor Red
    Write-Host "Installing Python..." -ForegroundColor Yellow
    
    # Try winget first (Windows 11/modern Windows 10)
    if (Test-CommandExists "winget") {
        Write-Host "Using winget to install Python..." -ForegroundColor Cyan
        winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    }
    elseif (Test-CommandExists "choco") {
        Write-Host "Using Chocolatey to install Python..." -ForegroundColor Cyan
        choco install python -y
    }
    else {
        Write-Host "ERROR: Could not automatically install Python." -ForegroundColor Red
        Write-Host "Please install Python manually from https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Refresh environment variables
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    
    # Verify installation
    if (-not (Test-CommandExists "python")) {
        Write-Host "ERROR: Python installation failed or PATH not updated." -ForegroundColor Red
        Write-Host "Please restart your terminal and try again." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    $pythonVersion = Get-PythonVersion
    Write-Host "OK Python installed successfully (version $pythonVersion)" -ForegroundColor Green
}

Write-Host ""

# Check for uv
Write-Host "[3/5] Checking for uv..." -ForegroundColor Yellow
if (Test-CommandExists "uv") {
    Write-Host "OK uv is installed" -ForegroundColor Green
}
else {
    Write-Host "X uv is not installed" -ForegroundColor Red
    Write-Host "Installing uv using official installer..." -ForegroundColor Yellow
    
    try {
        Write-Host "Downloading and installing uv..." -ForegroundColor Cyan
        powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        # Also check in user's local bin directory
        $uvPath = "$env:USERPROFILE\.cargo\bin"
        if (Test-Path $uvPath) {
            $env:Path = "$uvPath;$env:Path"
        }
        
        if (-not (Test-CommandExists "uv")) {
            Write-Host "ERROR: uv installation failed or PATH not updated." -ForegroundColor Red
            Write-Host "Please restart your terminal and try again." -ForegroundColor Yellow
            exit 1
        }
        
        Write-Host "OK uv installed successfully" -ForegroundColor Green
    }
    catch {
        Write-Host "ERROR: Failed to install uv: $_" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# Run uv sync to install dependencies
Write-Host "[4/5] Running uv sync..." -ForegroundColor Yellow
try {
    uv sync
    Write-Host "OK uv sync completed successfully" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: uv sync failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Install tool as a global tool
Write-Host "[5/5] Installing $ToolName tool globally..." -ForegroundColor Yellow
try {
    uv tool install . --force
    Write-Host "OK $ToolName tool installed successfully" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Failed to install $ToolName tool: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Verifying installation..." -ForegroundColor Yellow
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Run tool --help to verify installation
try {
    & $ToolName --help
}
catch {
    Write-Host "ERROR: $ToolName verification failed: $_" -ForegroundColor Red
    Write-Host "Try restarting your terminal and running '$ToolName --help'" -ForegroundColor Yellow
    exit 1
}
