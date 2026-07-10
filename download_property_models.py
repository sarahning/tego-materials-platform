#!/usr/bin/env python3
"""Preload and cache the local CPU property-prediction engine."""

import os

os.environ.setdefault("TEGO_PROPERTY_DEVICE", "cpu")
os.environ.setdefault("DGLBACKEND", "pytorch")

from backend.property_prediction_service import get_predictor, get_predictor_status

if __name__ == "__main__":
    get_predictor()
    print("[OK] Tego property engine is ready.")
    print(get_predictor_status())
