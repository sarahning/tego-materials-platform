"""Exact Hofmann renderer adapter.

The original Tego renderer used ``hofmann.StructureScene`` directly.  The
property-prediction environment runs Python 3.9, while current Hofmann releases
require Python 3.11+.  To preserve the original Hofmann output instead of
substituting a look-alike renderer, this module supports two execution modes:

1. In-process Hofmann, when the current Python can import it.
2. A local Hofmann rendering service (default http://127.0.0.1:7862), running
   in a separate Python 3.13 conda environment.

Both modes execute the same original StructureScene/BondSpec rendering logic.
"""

import json
import os
from pathlib import Path
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import matplotlib

matplotlib.use("Agg")

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element
from pymatgen.io.cif import CifWriter

try:
    from hofmann import BondSpec, StructureScene

    LOCAL_HOFMANN_AVAILABLE = True
    LOCAL_HOFMANN_ERROR = ""
except Exception as exc:  # Expected in the Python 3.9 property environment.
    StructureScene = None
    BondSpec = None
    LOCAL_HOFMANN_AVAILABLE = False
    LOCAL_HOFMANN_ERROR = f"{type(exc).__name__}: {exc}"

HOFMANN_SERVICE_URL = os.getenv(
    "TEGO_HOFMANN_URL",
    "http://127.0.0.1:7862",
).rstrip("/")

# Kept for compatibility with old imports.  Runtime status should use
# renderer_status(), because a remote service may start after module import.
HOFMANN_AVAILABLE = LOCAL_HOFMANN_AVAILABLE


def _bond_spec(sp1: str, sp2: str, max_len: float):
    """Build BondSpec while supporting multiple Hofmann call signatures."""
    try:
        return BondSpec(species=(sp1, sp2), max_length=max_len)
    except TypeError:
        try:
            return BondSpec((sp1, sp2), max_len)
        except TypeError:
            return BondSpec(sp1, sp2, max_len)


def build_bonds_from_structure(structure: Structure, scale: float = 1.12):
    """Original Tego automatic covalent-radius bond construction."""
    if not LOCAL_HOFMANN_AVAILABLE:
        return []

    species = sorted({str(site.specie.symbol) for site in structure.sites})
    radii = {}
    for sp in species:
        try:
            radius = getattr(Element(sp), "covalent_radius", None)
            radii[sp] = float(radius) if radius is not None else 1.25
        except Exception:
            radii[sp] = 1.25

    bonds = []
    for index, sp1 in enumerate(species):
        for sp2 in species[index:]:
            bonds.append(
                _bond_spec(
                    sp1,
                    sp2,
                    scale * (radii[sp1] + radii[sp2]),
                )
            )
    return bonds


def _render_three_views_local(
    structure: Structure,
    out_dir: Path,
    prefix: str,
    zoom: float,
) -> List[Path]:
    """Run the exact renderer from the original Tego web project."""
    if not LOCAL_HOFMANN_AVAILABLE:
        raise RuntimeError(
            "Hofmann cannot be imported in the current interpreter: "
            + LOCAL_HOFMANN_ERROR
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    bonds = build_bonds_from_structure(structure)
    directions = {
        "view_100": (1, 0, 0),
        "view_010": (0, 1, 0),
        "view_001": (0, 0, 1),
    }

    paths: List[Path] = []
    for name, direction in directions.items():
        output_path = out_dir / f"{prefix}_{name}.png"
        scene = StructureScene.from_pymatgen(structure, bonds)
        scene.view.look_along(direction)
        scene.view.zoom = zoom
        scene.view.perspective = 0.0
        scene.render_mpl(str(output_path))
        paths.append(output_path)
    return paths


def _post_json(url: str, payload: Dict, timeout: float) -> Dict:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Hofmann renderer HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            "The local Hofmann service is not reachable at "
            f"{HOFMANN_SERVICE_URL}. Start the dual-environment launcher."
        ) from exc

    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("Hofmann renderer returned an invalid response.")
    return parsed


def _render_three_views_remote(
    structure: Structure,
    out_dir: Path,
    prefix: str,
    zoom: float,
) -> List[Path]:
    """Ask the Python 3.13 service to execute the original Hofmann renderer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cif_text = str(CifWriter(structure, symprec=None))
    response = _post_json(
        f"{HOFMANN_SERVICE_URL}/render-three-views",
        {
            "cif": cif_text,
            "output_dir": str(out_dir.resolve()),
            "prefix": str(prefix),
            "zoom": float(zoom),
        },
        timeout=180.0,
    )

    file_names = response.get("files", [])
    paths = [out_dir / str(name) for name in file_names]
    missing = [str(path) for path in paths if not path.exists()]
    if len(paths) != 3 or missing:
        raise RuntimeError(
            "Hofmann renderer did not produce all three images. "
            f"files={file_names}, missing={missing}"
        )
    return paths


def _remote_health(timeout: float = 0.8) -> Dict:
    try:
        with urlopen(f"{HOFMANN_SERVICE_URL}/health", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("ok"):
            return data
    except Exception:
        pass
    return {"ok": False}


def renderer_status() -> Dict:
    """Return the active rendering mode without exposing it in the public UI."""
    if LOCAL_HOFMANN_AVAILABLE:
        return {
            "available": True,
            "mode": "in_process",
            "service_url": None,
            "error": None,
        }

    health = _remote_health()
    if health.get("ok"):
        return {
            "available": True,
            "mode": "local_service",
            "service_url": HOFMANN_SERVICE_URL,
            "error": None,
        }

    return {
        "available": False,
        "mode": "unavailable",
        "service_url": HOFMANN_SERVICE_URL,
        "error": LOCAL_HOFMANN_ERROR or "Local Hofmann service is offline.",
    }


def render_three_views(
    structure: Structure,
    out_dir: Path,
    prefix: str,
    zoom: float = 1.20,
) -> List[Path]:
    """Render true Hofmann [100], [010], and [001] images.

    No visual imitation or Matplotlib fallback is used.  If Hofmann is not
    available in the current Python, the request is delegated to the dedicated
    Hofmann service.
    """
    if LOCAL_HOFMANN_AVAILABLE:
        return _render_three_views_local(structure, out_dir, prefix, zoom)
    return _render_three_views_remote(structure, out_dir, prefix, zoom)
