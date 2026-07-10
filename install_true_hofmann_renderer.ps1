$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$rendererEnv = "tego-hofmann"

Write-Host "[Tego] Creating the dedicated Hofmann renderer environment..."
Write-Host "[Tego] Environment: $rendererEnv"

$existing = conda env list | Select-String -Pattern "^$rendererEnv\s"
if (-not $existing) {
    conda create -n $rendererEnv python=3.13 pip -y
}

conda run -n $rendererEnv python -m pip install --upgrade pip
conda run -n $rendererEnv python -m pip install "hofmann[pymatgen]" fastapi "uvicorn[standard]"

Write-Host "[Tego] Verifying exact Hofmann imports..."
conda run -n $rendererEnv python -c "from hofmann import StructureScene, BondSpec; import pymatgen, fastapi, uvicorn; print('Hofmann renderer environment OK')"

Write-Host ""
Write-Host "[DONE] The true Hofmann renderer is ready."
Write-Host "Start the complete application with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\run_windows_cpu_true_hofmann.ps1"
