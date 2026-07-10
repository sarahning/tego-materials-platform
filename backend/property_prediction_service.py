"""Lazy, reusable property-prediction service for the Tego web application.

The web layer exposes only Tego-facing property names. Third-party checkpoint
names stay inside the backend implementation and are never returned to the UI.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

from .property_prediction_engine import MaterialPropertyPredictor

_ENGINE: Optional[MaterialPropertyPredictor] = None
_ENGINE_LOCK = threading.RLock()
_ENGINE_STATE: Dict[str, Any] = {
    "status": "idle",
    "device": None,
    "error": None,
}


def get_predictor_status() -> Dict[str, Any]:
    """Return a public status object without revealing implementation names."""
    with _ENGINE_LOCK:
        return {
            "status": _ENGINE_STATE["status"],
            "device": _ENGINE_STATE["device"],
            "error": _ENGINE_STATE["error"],
            "engine": "Tego Property Intelligence",
        }


def get_predictor() -> MaterialPropertyPredictor:
    """Load the three property models once, then reuse the same instance."""
    global _ENGINE

    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE

        requested_device = os.environ.get("TEGO_PROPERTY_DEVICE", "cpu").strip().lower() or "cpu"
        _ENGINE_STATE.update(status="loading", device=requested_device, error=None)
        try:
            _ENGINE = MaterialPropertyPredictor(device=requested_device, verbose=True)
        except Exception as exc:
            _ENGINE_STATE.update(
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        _ENGINE_STATE.update(status="ready", device=_ENGINE.device, error=None)
        return _ENGINE


def _magnetic_label(value: float) -> str:
    if value < 0.005:
        return "低局域磁矩响应"
    if value < 0.05:
        return "中等局域磁矩响应"
    return "较强局域磁矩响应"


def _band_gap_label(value: float) -> str:
    if value <= 0.05:
        return "金属或近零带隙"
    if value < 0.8:
        return "窄带隙材料"
    if value < 3.0:
        return "半导体带隙区间"
    return "宽带隙材料"


def _dielectric_label(value: float) -> str:
    if value < 5:
        return "低介电响应"
    if value < 20:
        return "中等介电响应"
    return "较高介电响应"


def to_public_payload(result: Any, *, source_name: Optional[str] = None) -> Dict[str, Any]:
    """Convert the internal result into a stable, product-facing API schema."""
    mag_density = float(result.chgnet_local_abs_mag_density_muB_A3)
    band_gap = float(result.alignn_mbj_band_gap_eV)
    dielectric = float(result.alignn_dfpt_max_static_dielectric)
    site_moments = [float(x) for x in result.chgnet_site_magmoms_muB]

    return {
        "source_name": source_name,
        "formula": result.formula,
        "n_sites": int(result.n_sites),
        "volume_A3": float(result.volume_A3),
        "magnetic_moment_density_muB_A3": mag_density,
        "local_absolute_moment_muB": float(result.chgnet_local_abs_moment_muB),
        "mean_site_moment_muB": float(result.chgnet_mean_site_magmom_muB),
        "max_site_moment_muB": float(result.chgnet_max_site_magmom_muB),
        "site_moments_muB": site_moments,
        "band_gap_eV": band_gap,
        "max_static_dielectric": dielectric,
        "interpretation": {
            "magnetic": _magnetic_label(mag_density),
            "band_gap": _band_gap_label(band_gap),
            "dielectric": _dielectric_label(dielectric),
        },
        "engine": {
            "name": "Tego Property Intelligence",
            "version": "1.0",
            "device": result.device.upper(),
        },
        "notices": [
            "磁性结果为局域绝对磁矩密度，不等同于考虑自旋正负抵消后的净磁矩密度。",
            "带隙与介电常数用于快速筛选和趋势判断，关键候选建议进一步进行高精度计算或实验验证。",
            "预测针对输入 CIF 中的当前晶胞与原子排布，不会自动执行结构弛豫。",
        ],
    }
