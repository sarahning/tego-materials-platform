#!/usr/bin/env python3
"""Lightweight environment and integration check without running inference."""

import importlib
import os
import sys

os.environ.setdefault("TEGO_PROPERTY_DEVICE", "cpu")
os.environ.setdefault("DGLBACKEND", "pytorch")

modules = [
    "fastapi",
    "uvicorn",
    "numpy",
    "pandas",
    "torch",
    "dgl",
    "yaml",
    "pydantic",
    "pymatgen",
    "chgnet",
    "alignn",
]

failed = []
for name in modules:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "available")
        print(f"[OK] {name}: {version}")
    except Exception as exc:
        failed.append((name, exc))
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")

try:
    from backend.main import app
    paths = {route.path for route in app.routes}
    required = {
        "/api/property-predictor/status",
        "/api/property-predictor/predict",
        "/api/candidates/{candidate_id}/predict-properties",
    }
    missing = required - paths
    if missing:
        failed.append(("routes", RuntimeError(str(sorted(missing)))))
        print(f"[FAIL] missing routes: {sorted(missing)}")
    else:
        print("[OK] property prediction routes registered")
except Exception as exc:
    failed.append(("backend.main", exc))
    print(f"[FAIL] backend.main: {type(exc).__name__}: {exc}")

if failed:
    print("\nEnvironment check failed.")
    sys.exit(1)
print("\n[OK] Tego property platform integration is ready.")
