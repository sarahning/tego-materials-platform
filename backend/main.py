import json
import logging
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    CANDIDATE_VIEW_DIR,
    DATABASE_CSV,
    RETRIEVAL_CSVS,
    FRONTEND_DIR,
    PROPERTY_KEYS,
    PROPERTY_SPECS,
    RUNTIME_DIR,
    WYCKOFF_VIEW_DIR,
    PROPERTY_PLOT_DIR,
    ensure_runtime_dirs,
)
from .llm_parser import parse_function_description
from .rendering import render_three_views, renderer_status
from .retrieval_core import load_database, retrieve_candidates
from .property_plot_utils import build_candidate_property_plots
from .property_prediction_service import get_predictor, get_predictor_status, to_public_payload
from .structure_utils import (
    build_basic_parameters,
    load_structure_from_cif,
    property_rows,
    render_structure_viewer_html,
    sanitize_public_cif_text,
    structure_to_cif_text,
)
from .wyckoff_utils import analyze_wyckoff_with_images

ensure_runtime_dirs()

LOGGER = logging.getLogger("tego.web")

app = FastAPI(title="璇玑 Tego Materials Studio", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

STATE: Dict = {
    "session_id": None,
    "candidates": {},
    "ordered_ids": [],
}


class ParseRequest(BaseModel):
    text: str = ""


class GenerateRequest(BaseModel):
    targets: Dict[str, Optional[float]] = Field(default_factory=dict)
    weights: Dict[str, float] = Field(default_factory=dict)
    topk: int = 5
    function_text: str = ""


class PredictionRequest(BaseModel):
    cif: str = Field(min_length=20)
    source_name: Optional[str] = None


def _reset_generation_runtime(session_id: str) -> Path:
    for folder in (CANDIDATE_VIEW_DIR, WYCKOFF_VIEW_DIR, PROPERTY_PLOT_DIR):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    session_dir = CANDIDATE_VIEW_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _asset_url(bucket: str, *parts: str) -> str:
    clean = "/".join(str(p).replace("\\", "/").strip("/") for p in parts)
    return f"/api/assets/{bucket}/{clean}"


def _safe_file(root: Path, rel_path: str) -> Path:
    root = root.resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=404, detail="Not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return target


def _get_candidate(candidate_id: str) -> Dict:
    cand = STATE["candidates"].get(candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return cand


def _render_hero_crystal_html(cif_text: str) -> str:
    cif_js = json.dumps(str(cif_text or ""))
    viewer_id = f"hero_viewer_{uuid.uuid4().hex}"
    return f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<script src="https://3dmol.csb.pitt.edu/build/3Dmol-min.js"></script>
<style>
html, body {{
  margin:0; padding:0; width:100%; height:100%; overflow:hidden;
  background: transparent;
}}
#{viewer_id} {{
  width:100%; height:100%;
  background: transparent;
}}
</style>
</head>
<body>
<div id="{viewer_id}"></div>
<script>
try {{
  if (window.$3Dmol) {{
    const viewer = $3Dmol.createViewer('{viewer_id}', {{ backgroundColor: 'rgba(255,255,255,0)' }});
    const model = viewer.addModel({cif_js}, 'cif');
    viewer.setStyle({{}}, {{
      sphere: {{ scale: 0.34, color: '#2f80ed', opacity: 0.94 }},
      stick: {{ radius: 0.11, color: '#85c7ff', opacity: 0.86 }}
    }});
    viewer.addUnitCell(model);
    try {{ viewer.replicateUnitCell(1, 1, 1, model, true, false); }} catch(e) {{}}
    viewer.zoomTo();
    viewer.zoom(0.82);
    viewer.rotate(16, {{x: 1, y: 0, z: 0}});
    viewer.rotate(-10, {{x: 0, y: 0, z: 1}});
    viewer.render();
    viewer.spin('y', 0.48);
  }}
}} catch (e) {{}}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def get_config():
    return {
        "properties": PROPERTY_SPECS,
        "database_ready": any(p.exists() for p in RETRIEVAL_CSVS),
        "hofmann_available": renderer_status()["available"],
        "hofmann_renderer": renderer_status(),
        "property_predictor": get_predictor_status(),
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "database_ready": any(p.exists() for p in RETRIEVAL_CSVS),
        "hofmann_available": renderer_status()["available"],
        "hofmann_renderer": renderer_status(),
        "property_predictor": get_predictor_status(),
    }


@app.post("/api/parse-function")
def parse_function(req: ParseRequest):
    return parse_function_description(req.text)


@app.get("/api/hero-crystal")
def hero_crystal():
    try:
        df = load_database(RETRIEVAL_CSVS)
        df = df[df["cif"].notna()]
        df = df[df["cif"].astype(str).str.strip() != ""]
        if len(df) == 0:
            raise ValueError("empty")
        idx = random.randrange(len(df))
        row = df.iloc[idx]
        title = str(row.get("material_id", "Crystal preview"))
        return {"title": title, "viewer_html": _render_hero_crystal_html(str(row.get("cif", "")))}
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc


@app.post("/api/submit-design")
def submit_design(req: GenerateRequest):
    started = time.perf_counter()
    session_id = uuid.uuid4().hex[:12]
    session_dir = _reset_generation_runtime(session_id)

    targets = {key: req.targets.get(key, None) for key in PROPERTY_KEYS}
    weights = {key: float(req.weights.get(key, 0.0) or 0.0) for key in PROPERTY_KEYS}

    # 前端可能只给了权重但没有目标值；这种属性不参与检索。
    for key in PROPERTY_KEYS:
        if targets.get(key) is None:
            weights[key] = 0.0

    has_active_target = any(
        targets.get(key) is not None and float(weights.get(key, 0.0) or 0.0) > 0
        for key in PROPERTY_KEYS
    )

    if req.function_text.strip() and not has_active_target:
        parsed = parse_function_description(req.function_text)
        targets.update({k: parsed["targets"].get(k) for k in PROPERTY_KEYS})
        weights.update({k: parsed["weights"].get(k, 0.0) for k in PROPERTY_KEYS})
        for key in PROPERTY_KEYS:
            if targets.get(key) is None:
                weights[key] = 0.0
        has_active_target = any(
            targets.get(key) is not None and float(weights.get(key, 0.0) or 0.0) > 0
            for key in PROPERTY_KEYS
        )

    retrieval_started = time.perf_counter()
    try:
        summary = retrieve_candidates(targets, weights, int(req.topk), RETRIEVAL_CSVS)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="生成失败") from exc
    retrieval_seconds = time.perf_counter() - retrieval_started

    render_started = time.perf_counter()
    STATE["session_id"] = session_id
    STATE["candidates"] = {}
    STATE["ordered_ids"] = []
    output_candidates = []

    for item in summary["results"]:
        try:
            structure = load_structure_from_cif(item["cif_path"])
            formula = structure.composition.reduced_formula
            cand_dir = session_dir / item["candidate_id"]
            img_paths = render_three_views(structure, cand_dir, "candidate", zoom=1.20)
            image_urls = [_asset_url("candidate", session_id, item["candidate_id"], p.name) for p in img_paths]
            basic_params = build_basic_parameters(structure)
            rows = property_rows(item["properties"])
        except Exception:
            formula = str(item["material_id"])
            image_urls = []
            basic_params = []
            rows = property_rows(item["properties"])

        cand = {
            **item,
            "formula": formula,
            "title": f"{formula}",
            "image_urls": image_urls,
            "basic_parameters": basic_params,
            "property_rows": rows,
        }
        STATE["candidates"][item["candidate_id"]] = cand
        STATE["ordered_ids"].append(item["candidate_id"])
        output_candidates.append(
            {
                "candidate_id": item["candidate_id"],
                "rank": item["rank"],
                "material_id": item["material_id"],
                "formula": formula,
                "title": cand["title"],
                "score": item["score"],
                "image_urls": image_urls,
                "property_rows": rows,
                "basic_parameters": basic_params[:5],
            }
        )

    render_seconds = time.perf_counter() - render_started
    total_seconds = time.perf_counter() - started

    return {
        "session_id": session_id,
        "candidates": output_candidates,
        "timing": {
            "retrieval_seconds": retrieval_seconds,
            "render_seconds": render_seconds,
            "total_seconds": total_seconds,
        },
    }


@app.get("/api/candidates/{candidate_id}")
def candidate_detail(candidate_id: str):
    cand = _get_candidate(candidate_id)
    try:
        structure = load_structure_from_cif(cand["cif_path"])
        viewer_html = render_structure_viewer_html(structure)
        cif_text = Path(cand["cif_path"]).read_text(encoding="utf-8")
        if not cif_text.strip():
            cif_text = structure_to_cif_text(structure)
        formula = structure.composition.reduced_formula
        cif_text = sanitize_public_cif_text(cif_text, formula)
        basic = build_basic_parameters(structure)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Candidate structure cannot be opened.") from exc

    return {
        "candidate_id": candidate_id,
        "title": cand["formula"],
        "formula": cand["formula"],
        "rank": cand["rank"],
        "viewer_html": viewer_html,
        "cif_text": cif_text,
        "basic_parameters": basic,
        "property_rows": cand["property_rows"],
    }


@app.get("/api/candidates/{candidate_id}/properties")
def candidate_properties(candidate_id: str):
    cand = _get_candidate(candidate_id)
    try:
        plots = build_candidate_property_plots(
            candidate_id=candidate_id,
            properties=cand.get("properties", {}),
            database_csv=RETRIEVAL_CSVS,
        )
    except Exception:
        plots = [
            {
                "key": row["key"],
                "name": row["name"],
                "unit": row.get("unit", ""),
                "title": f"{row['name']} 数据集位置图",
                "url": None,
                "note": "暂无可用分布数据",
                "stats": None,
            }
            for row in cand["property_rows"]
        ]

    return {
        "candidate_id": candidate_id,
        "title": cand["formula"],
        "formula": cand["formula"],
        "property_rows": cand["property_rows"],
        "basic_parameters": cand["basic_parameters"],
        "property_plots": plots,
    }


@app.get("/api/candidates/{candidate_id}/wyckoff")
def candidate_wyckoff(candidate_id: str):
    cand = _get_candidate(candidate_id)
    try:
        structure = load_structure_from_cif(cand["cif_path"])
        result = analyze_wyckoff_with_images(structure)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Wyckoff analysis cannot be completed.") from exc

    full_urls = [_asset_url("wyckoff", "current", name) for name in result["full_image_files"]]
    groups = []
    for g in result["groups"]:
        groups.append(
            {
                **{k: v for k, v in g.items() if k != "image_files"},
                "image_urls": [_asset_url("wyckoff", "current", name) for name in g.get("image_files", [])],
            }
        )

    return {
        "candidate_id": candidate_id,
        "title": cand["formula"],
        "formula": cand["formula"],
        "full_image_urls": full_urls,
        "groups": groups,
    }


@app.get("/api/candidates/{candidate_id}/cif")
def candidate_cif_download(candidate_id: str):
    cand = _get_candidate(candidate_id)
    try:
        structure = load_structure_from_cif(cand["cif_path"])
        formula = structure.composition.reduced_formula
        cif_text = Path(cand["cif_path"]).read_text(encoding="utf-8")
        if not cif_text.strip():
            cif_text = structure_to_cif_text(structure)
        cif_text = sanitize_public_cif_text(cif_text, formula)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="CIF cannot be opened.") from exc
    filename = ''.join(ch if ch.isalnum() or ch in ['_', '-'] else '_' for ch in formula) or 'candidate_structure'
    headers = {"Content-Disposition": f"attachment; filename={filename}.cif"}
    return Response(content=cif_text, media_type="chemical/x-cif; charset=utf-8", headers=headers)


@app.get("/api/property-predictor/status")
def property_predictor_status():
    return get_predictor_status()


@app.post("/api/property-predictor/predict")
def predict_properties(req: PredictionRequest):
    try:
        predictor = get_predictor()
        structure = predictor.structure_from_cif_text(req.cif)
        result = predictor.predict_structure(structure)
        payload = to_public_payload(result, source_name=req.source_name)
        payload["viewer_html"] = render_structure_viewer_html(structure)
        payload["basic_parameters"] = build_basic_parameters(structure)
        return payload
    except Exception as exc:
        LOGGER.exception("Property prediction failed for custom CIF")
        raise HTTPException(
            status_code=422,
            detail="性质预测失败，请检查 CIF 格式、结构有序性与本地计算环境。",
        ) from exc


@app.post("/api/candidates/{candidate_id}/predict-properties")
def predict_candidate_properties(candidate_id: str):
    cand = _get_candidate(candidate_id)
    try:
        structure = load_structure_from_cif(cand["cif_path"])
        predictor = get_predictor()
        result = predictor.predict_structure(structure)
        payload = to_public_payload(result, source_name=cand.get("formula") or candidate_id)
        payload["candidate_id"] = candidate_id
        payload["viewer_html"] = render_structure_viewer_html(structure)
        payload["basic_parameters"] = build_basic_parameters(structure)
        return payload
    except Exception as exc:
        LOGGER.exception("Property prediction failed for candidate %s", candidate_id)
        raise HTTPException(
            status_code=422,
            detail="候选结构性质预测失败，请检查本地计算环境后重试。",
        ) from exc


@app.get("/api/assets/{bucket}/{rel_path:path}")
def assets(bucket: str, rel_path: str):
    if bucket == "candidate":
        return FileResponse(_safe_file(CANDIDATE_VIEW_DIR, rel_path))
    if bucket == "wyckoff":
        return FileResponse(_safe_file(WYCKOFF_VIEW_DIR, rel_path))
    if bucket == "property":
        return FileResponse(_safe_file(PROPERTY_PLOT_DIR, rel_path))
    raise HTTPException(status_code=404, detail="Not found")
