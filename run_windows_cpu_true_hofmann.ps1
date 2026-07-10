$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# The active shell must already be in the working property-prediction environment.
$propertyPython = (Get-Command python -ErrorAction Stop).Source
$condaBase = (conda info --base).Trim()
$rendererPython = Join-Path $condaBase "envs\tego-hofmann\python.exe"

if (-not (Test-Path $rendererPython)) {
    throw "The dedicated Hofmann environment was not found at $rendererPython. Run install_true_hofmann_renderer.ps1 first."
}

Write-Host "[Tego] Property Python: $propertyPython"
Write-Host "[Tego] Hofmann Python: $rendererPython"

# Verify that the foreground Python is the already configured model environment.
& $propertyPython -c "import chgnet, alignn, torch, dgl; print('[Tego] Property environment OK')"
if ($LASTEXITCODE -ne 0) {
    throw "The active Python cannot import the property models. Activate the website environment first."
}

$env:TEGO_PROPERTY_DEVICE = "cpu"
$env:DGLBACKEND = "pytorch"
$env:TEGO_HOFMANN_URL = "http://127.0.0.1:7862"
$env:TEGO_HOFMANN_ALLOWED_ROOT = $PSScriptRoot

$defaultDataset = Join-Path $PSScriptRoot "mp20_with_jav_dielectric\mp20_with_jav_epsx_epsy_epsz.csv"
if (-not $env:RETRIEVAL_CSVS) {
    $env:RETRIEVAL_CSVS = $defaultDataset
}

$rendererOut = Join-Path $PSScriptRoot "runtime\hofmann_renderer.stdout.log"
$rendererErr = Join-Path $PSScriptRoot "runtime\hofmann_renderer.stderr.log"
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "runtime") | Out-Null

Write-Host "[Tego] Starting true Hofmann service at http://127.0.0.1:7862 ..."
$rendererProcess = Start-Process `
    -FilePath $rendererPython `
    -ArgumentList @("-m", "uvicorn", "hofmann_renderer_service:app", "--host", "127.0.0.1", "--port", "7862", "--workers", "1") `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $rendererOut `
    -RedirectStandardError $rendererErr `
    -PassThru

try {
    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        if ($rendererProcess.HasExited) {
            $errorText = ""
            if (Test-Path $rendererErr) {
                $errorText = Get-Content $rendererErr -Raw
            }
            throw "The Hofmann service exited during startup. $errorText"
        }

        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:7862/health" -TimeoutSec 1
            if ($health.ok) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        throw "The Hofmann service did not become ready. Check runtime\hofmann_renderer.stderr.log."
    }

    Write-Host "[Tego] Exact Hofmann renderer: READY"
    Write-Host "[Tego] Device: CPU"
    Write-Host "[Tego] Dataset: $env:RETRIEVAL_CSVS"
    Write-Host "[Tego] Open: http://127.0.0.1:7860"
    Write-Host ""

    & $propertyPython -m uvicorn backend.main:app --host 0.0.0.0 --port 7860 --workers 1
}
finally {
    if ($rendererProcess -and -not $rendererProcess.HasExited) {
        Write-Host "[Tego] Stopping Hofmann renderer..."
        Stop-Process -Id $rendererProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
