$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:TEGO_PROPERTY_DEVICE = "cpu"
$env:DGLBACKEND = "pytorch"

$defaultDataset = Join-Path $PSScriptRoot "mp20_with_jav_dielectric\mp20_with_jav_epsx_epsy_epsz.csv"
if (-not $env:RETRIEVAL_CSVS) {
    $env:RETRIEVAL_CSVS = $defaultDataset
}

Write-Host "[Tego] Device: CPU"
Write-Host "[Tego] Dataset: $env:RETRIEVAL_CSVS"
Write-Host "[Tego] Open: http://127.0.0.1:7860"

python -m uvicorn backend.main:app --host 0.0.0.0 --port 7860 --workers 1
