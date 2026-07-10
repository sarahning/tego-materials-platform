$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/5] Installing CPU PyTorch..."
python -m pip install torch==2.2.1 --index-url https://download.pytorch.org/whl/cpu

Write-Host "[2/5] Installing DGL runtime dependencies..."
python -m pip install -c constraints-cpu.txt torchdata==0.7.1 dgl==2.2.1 packaging==24.2 PyYAML==6.0.2

Write-Host "[3/5] Installing property prediction packages..."
python -m pip install -c constraints-cpu.txt chgnet==0.3.8 alignn==2026.5.20

Write-Host "[4/5] Restoring NumPy 1.x compatibility..."
python -m pip install --force-reinstall --no-cache-dir numpy==1.26.4

Write-Host "[5/5] Verifying imports..."
$env:DGLBACKEND = "pytorch"
python -c "import numpy, torch, dgl, yaml, pydantic; from chgnet.model.model import CHGNet; from alignn import pretrained; print('NumPy:', numpy.__version__); print('Torch:', torch.__version__); print('DGL:', dgl.__version__); print('CPU property environment OK')"
python -m pip check
