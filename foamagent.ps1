# foamagent.ps1 — Foam-Agent zero-install MCP launcher for Windows
param(
    [string]$Mode = "mcp",
    [string]$Port = "",
    [string]$Host_ = "0.0.0.0",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

# --- Load .env file if exists ---
$envFile = Join-Path $ProjectDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $key, $value = $line -split "=", 2
            $key = $key.Trim()
            $value = $value.Trim()
            if ($key -and $value) {
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
}

# --- Step 1: Create venv if missing ---
if (-not (Test-Path $PythonExe)) {
    Write-Host "[Foam-Agent] Creating virtual environment..." -ForegroundColor Cyan
    uv venv $VenvDir --python 3.12
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Foam-Agent] ERROR: uv venv failed. Install uv: https://docs.astral.sh/uv/" -ForegroundColor Red
        exit 1
    }

    Write-Host "[Foam-Agent] Installing dependencies..." -ForegroundColor Cyan
    uv pip install -e $ProjectDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Foam-Agent] ERROR: pip install failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "[Foam-Agent] Environment ready." -ForegroundColor Green
}

# --- Step 2: Check API keys ---
$hasKey = $false
if ($env:OPENAI_API_KEY) { $hasKey = $true }
if ($env:ANTHROPIC_API_KEY) { $hasKey = $true }
if (-not $hasKey) {
    Write-Host "[Foam-Agent] WARNING: No OPENAI_API_KEY or ANTHROPIC_API_KEY set. LLM calls will fail." -ForegroundColor Yellow
}

# --- Step 3: Launch ---
$env:PYTHONPATH = $ProjectDir

# Port resolution: parameter > env var > mode default
if (-not $Port) {
    if ($env:FOAMAGENT_PORT) { $Port = $env:FOAMAGENT_PORT }
    elseif ($Mode -eq "mcp") { $Port = "7860" }
    else { $Port = "5174" }
}

Write-Host "[Foam-Agent] Starting $Mode server on ${Host_}:${Port}..." -ForegroundColor Cyan

if ($Mode -eq "mcp") {
    & $PythonExe (Join-Path $ProjectDir "src\mcp\cli.py")
}
elseif ($Mode -eq "ws") {
    $args_ = @((Join-Path $ProjectDir "frontend\server.js"), "--port", ([int]$Port))
    if ($Dev) { $args_ += "--dev" }
    node @args_
}
elseif ($Mode -eq "health") {
    & $PythonExe (Join-Path $ProjectDir "app.py") --mode health --host $Host_ --port ([int]$Port)
}
else {
    Write-Host "[Foam-Agent] Unknown mode: $Mode (use mcp, ws, or health)" -ForegroundColor Red
    exit 1
}
