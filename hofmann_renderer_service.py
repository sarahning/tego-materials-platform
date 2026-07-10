"""Dedicated true-Hofmann renderer for the Tego web application.

Run this module in a Python 3.11+ environment containing
``hofmann[pymatgen]``.  The main property-prediction application can stay in
its Python 3.9 environment and send local rendering requests here.
"""

import os
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element
from hofmann import BondSpec, StructureScene

app = FastAPI(title="Tego local crystal renderer", version="1.0")

PROJECT_ROOT = Path(__file__).resolve().parent
ALLOWED_ROOT = Path(
    os.getenv("TEGO_HOFMANN_ALLOWED_ROOT", str(PROJECT_ROOT))
).resolve()


class RenderRequest(BaseModel):
    cif: str = Field(min_length=20)
    output_dir: str
    prefix: str = Field(min_length=1, max_length=160)
    zoom: float = Field(default=1.20, gt=0.05, lt=20.0)


def _safe_output_dir(raw_path: str) -> Path:
    output_dir = Path(raw_path).resolve()
    if output_dir != ALLOWED_ROOT and ALLOWED_ROOT not in output_dir.parents:
        raise HTTPException(
            status_code=403,
            detail="The requested output directory is outside the shared project root.",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _safe_prefix(prefix: str) -> str:
    cleaned = "".join(
        character
        for character in str(prefix)
        if character.isalnum() or character in {"_", "-"}
    )
    if not cleaned:
        raise HTTPException(status_code=422, detail="Invalid output prefix.")
    return cleaned[:160]


def _bond_spec(sp1: str, sp2: str, max_len: float):
    try:
        return BondSpec(species=(sp1, sp2), max_length=max_len)
    except TypeError:
        try:
            return BondSpec((sp1, sp2), max_len)
        except TypeError:
            return BondSpec(sp1, sp2, max_len)


def build_bonds_from_structure(structure: Structure, scale: float = 1.12):
    species = sorted({str(site.specie.symbol) for site in structure.sites})
    radii = {}
    for species_name in species:
        try:
            radius = getattr(Element(species_name), "covalent_radius", None)
            radii[species_name] = float(radius) if radius is not None else 1.25
        except Exception:
            radii[species_name] = 1.25

    bonds = []
    for index, species_1 in enumerate(species):
        for species_2 in species[index:]:
            bonds.append(
                _bond_spec(
                    species_1,
                    species_2,
                    scale * (radii[species_1] + radii[species_2]),
                )
            )
    return bonds


def render_three_views(
    structure: Structure,
    output_dir: Path,
    prefix: str,
    zoom: float,
) -> List[Path]:
    """Exact renderer copied from the user's original Tego web project."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bonds = build_bonds_from_structure(structure)
    directions = {
        "view_100": (1, 0, 0),
        "view_010": (0, 1, 0),
        "view_001": (0, 0, 1),
    }

    paths: List[Path] = []
    for name, direction in directions.items():
        output_path = output_dir / f"{prefix}_{name}.png"
        scene = StructureScene.from_pymatgen(structure, bonds)
        scene.view.look_along(direction)
        scene.view.zoom = zoom
        scene.view.perspective = 0.0
        scene.render_mpl(str(output_path))
        paths.append(output_path)
    return paths


@app.get("/health")
def health():
    return {
        "ok": True,
        "renderer": "hofmann",
        "allowed_root": str(ALLOWED_ROOT),
    }


@app.post("/render-three-views")
def render_endpoint(request: RenderRequest):
    try:
        structure = Structure.from_str(request.cif, fmt="cif")
        output_dir = _safe_output_dir(request.output_dir)
        prefix = _safe_prefix(request.prefix)
        paths = render_three_views(
            structure=structure,
            output_dir=output_dir,
            prefix=prefix,
            zoom=float(request.zoom),
        )
        return {
            "ok": True,
            "files": [path.name for path in paths],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Hofmann rendering failed: {type(exc).__name__}: {exc}",
        ) from exc
