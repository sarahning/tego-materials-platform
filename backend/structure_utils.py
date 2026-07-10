import json
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Union

from pymatgen.core import Structure
from pymatgen.io.cif import CifParser
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .config import PROPERTY_SPECS, PROPERTY_UNITS
from .retrieval_core import safe_float


def load_structure_from_cif(cif_path: Union[str, Path]) -> Structure:
    parser = CifParser(str(cif_path))
    structures = parser.parse_structures(primitive=False)
    if not structures:
        raise ValueError("CIF parsing failed.")
    return structures[0]


def structure_to_cif_text(structure: Structure) -> str:
    return structure.to(fmt="cif")


def sanitize_public_cif_text(cif_text: str, fallback_formula: str = "candidate_structure") -> str:
    """Remove database-like identifiers from CIF text before showing or downloading."""
    text = str(cif_text or "")
    safe_formula = re.sub(r"[^A-Za-z0-9_]+", "_", str(fallback_formula or "candidate_structure")).strip("_") or "candidate_structure"
    # Replace common Materials Project style identifiers without altering chemical formulas.
    text = re.sub(r"mp[-_][A-Za-z0-9_.-]+", safe_formula, text, flags=re.IGNORECASE)
    # Normalize data block when it became empty or identifier-like.
    lines = []
    data_seen = False
    for line in text.splitlines():
        if line.lower().startswith("data_"):
            lines.append(f"data_{safe_formula}")
            data_seen = True
        else:
            lines.append(line)
    if not data_seen:
        lines.insert(0, f"data_{safe_formula}")
    return "\n".join(lines).strip() + "\n"


def build_basic_parameters(structure: Structure) -> List[Dict[str, str]]:
    a, b, c = structure.lattice.abc
    alpha, beta, gamma = structure.lattice.angles
    try:
        sga = SpacegroupAnalyzer(structure, symprec=1e-2, angle_tolerance=5)
        spg_symbol = sga.get_space_group_symbol()
        spg_number = sga.get_space_group_number()
        crystal_system = sga.get_crystal_system().title()
    except Exception:
        spg_symbol = "Unknown"
        spg_number = "—"
        crystal_system = "Unknown"

    return [
        {"name": "最简化学式", "value": structure.composition.reduced_formula},
        {"name": "完整化学式", "value": structure.composition.formula},
        {"name": "原子位点数量", "value": str(len(structure))},
        {"name": "空间群", "value": f"{spg_symbol} ({spg_number})"},
        {"name": "晶系", "value": crystal_system},
        {"name": "晶格常数 a / b / c (Å)", "value": f"{a:.3f} / {b:.3f} / {c:.3f}"},
        {"name": "晶轴夹角 α / β / γ (°)", "value": f"{alpha:.2f} / {beta:.2f} / {gamma:.2f}"},
        {"name": "晶胞体积 (Å³)", "value": f"{structure.lattice.volume:.3f}"},
        {"name": "密度 (g/cm³)", "value": f"{structure.density:.3f}"},
    ]


def _fmt_prop_value(x: Optional[float]) -> str:
    val = safe_float(x)
    return "—" if val is None else f"{val:.6g}"


def property_rows(properties: Dict[str, Optional[float]]) -> List[Dict[str, str]]:
    rows = []
    for spec in PROPERTY_SPECS:
        key = spec["key"]
        unit = PROPERTY_UNITS.get(key, "")

        if key == "dielectric_constant":
            epsx = safe_float(properties.get("dielectric_epsx", None))
            epsy = safe_float(properties.get("dielectric_epsy", None))
            epsz = safe_float(properties.get("dielectric_epsz", None))
            if epsx is not None or epsy is not None or epsz is not None:
                value = f"εx {_fmt_prop_value(epsx)} / εy {_fmt_prop_value(epsy)} / εz {_fmt_prop_value(epsz)}"
            else:
                value = _fmt_prop_value(properties.get(key, None))
        else:
            value = _fmt_prop_value(properties.get(key, None))

        rows.append(
            {
                "key": key,
                "name": spec["label"],
                "value": value,
                "unit": unit,
            }
        )
    return rows


def render_structure_viewer_html(
    structure: Structure,
    supercell=(2, 2, 2),
    sphere_scale: float = 0.30,
    stick_radius: float = 0.10,
) -> str:
    """Industrial 3Dmol studio viewer with style/background controls."""
    formula = structure.composition.reduced_formula
    cif_text = sanitize_public_cif_text(structure_to_cif_text(structure), formula)
    cif_js = json.dumps(cif_text)
    formula_js = json.dumps(formula)
    element_js = json.dumps(sorted({str(site.specie.symbol) for site in structure}))
    viewer_id = f"viewer_{uuid.uuid4().hex}"
    return f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<script src="https://3dmol.csb.pitt.edu/build/3Dmol-min.js"></script>
<style>
:root {{
  --bg:#f4f5f7;
  --panel:#f8f9fb;
  --panel2:#eef1f5;
  --line:rgba(30,35,45,.14);
  --line-strong:rgba(30,35,45,.24);
  --text:#111827;
  --muted:#6b7280;
  --accent:#4b5563;
}}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; width:100%; height:100%; overflow:hidden; color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f7f8fa; }}
.studio {{ width:100%; height:100%; display:grid; grid-template-rows:54px 1fr 128px; border:1px solid var(--line-strong); background:#f7f8fa; }}
.toolbar {{ display:flex; align-items:center; justify-content:flex-start; gap:12px; padding:0 14px; border-bottom:1px solid var(--line-strong); background:linear-gradient(180deg,#fff,#eef1f5); }}
.controls {{ width:100%; display:flex; align-items:center; gap:8px; flex-wrap:nowrap; }}
.controls button[onclick="downloadPNG()"] {{ margin-left:auto; }}
.controls button[onclick="downloadPNG()"], .controls button[onclick="downloadJPG()"], .controls button[onclick="downloadHTML()"] {{ border-color:rgba(17,24,39,.24); background:#f8f9fb; font-weight:760; }}
.heading {{ display:flex; align-items:baseline; gap:10px; min-width:0; }}
.formula {{ font-size:22px; font-weight:850; letter-spacing:-.03em; white-space:nowrap; color:#111827; }}
.sub {{ font-size:12px; color:#6b7280; white-space:nowrap; }}

button,select,.check {{ height:34px; border:1px solid rgba(30,35,45,.16); background:rgba(255,255,255,.82); color:#1f2933; padding:0 10px; outline:none; font-size:12px; font-family:inherit; }}
button {{ cursor:pointer; }}
button:hover,select:hover,.check:hover {{ background:#fff; border-color:rgba(30,35,45,.34); }}
.check {{ display:inline-flex; align-items:center; gap:5px; }}
.stage {{ position:relative; overflow:hidden; background:radial-gradient(circle at 50% 40%, rgba(210,214,222,.34), transparent 42%), linear-gradient(135deg,#f8f9fb 0%,#eceff3 55%,#fff 100%); }}
.stage::before {{ content:""; position:absolute; inset:0; pointer-events:none; background:linear-gradient(rgba(0,0,0,.024) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,.024) 1px, transparent 1px); background-size:44px 44px; opacity:.78; }}
.stage::after {{ content:""; position:absolute; inset:0; pointer-events:none; box-shadow:0 0 0 1px rgba(255,255,255,.72) inset, 0 74px 120px rgba(30,35,45,.08) inset, 0 -74px 120px rgba(30,35,45,.08) inset; }}
.viewer {{ position:absolute; inset:0; z-index:1; }}
.ruler-top {{ position:absolute; left:0; top:0; right:0; height:13px; background:rgba(255,255,255,.96); border-bottom:1px solid rgba(30,35,45,.14); z-index:6; }}
.ruler-top::before {{ content:""; position:absolute; inset:0; background:linear-gradient(to right, transparent 24.8%, rgba(30,35,45,.64) 24.8%, rgba(30,35,45,.64) 25.2%, transparent 25.2%), linear-gradient(to right, transparent 49.8%, rgba(30,35,45,.64) 49.8%, rgba(30,35,45,.64) 50.2%, transparent 50.2%), linear-gradient(to right, transparent 74.8%, rgba(30,35,45,.64) 74.8%, rgba(30,35,45,.64) 75.2%, transparent 75.2%); }}
.ruler-left {{ position:absolute; left:0; top:13px; bottom:0; width:13px; background:rgba(255,255,255,.96); border-right:1px solid rgba(30,35,45,.14); z-index:6; }}
.ruler-left::before {{ content:""; position:absolute; inset:0; background:linear-gradient(to bottom, transparent 24.8%, rgba(30,35,45,.64) 24.8%, rgba(30,35,45,.64) 25.2%, transparent 25.2%), linear-gradient(to bottom, transparent 49.8%, rgba(30,35,45,.64) 49.8%, rgba(30,35,45,.64) 50.2%, transparent 50.2%), linear-gradient(to bottom, transparent 74.8%, rgba(30,35,45,.64) 74.8%, rgba(30,35,45,.64) 75.2%, transparent 75.2%); }}
.inspector {{ position:absolute; right:18px; top:32px; width:244px; border:1px solid rgba(30,35,45,.14); background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(245,247,250,.88)); box-shadow:0 18px 44px rgba(30,35,45,.14); z-index:10; pointer-events:none; }}
.inspector-head {{ padding:9px 11px; border-bottom:1px solid rgba(30,35,45,.10); font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:#475569; }}
.inspector-body {{ padding:10px 11px 12px; font-size:12px; line-height:1.65; color:#1f2933; }}
.axis-panel,.mini-cell-panel {{ position:absolute; border:1px solid rgba(30,35,45,.14); background:rgba(255,255,255,.82); box-shadow:0 18px 44px rgba(30,35,45,.12),0 0 0 1px rgba(255,255,255,.8) inset; z-index:9; }}
.axis-panel {{ left:22px; bottom:22px; width:148px; height:148px; }}
.mini-cell-panel {{ right:18px; bottom:22px; width:240px; height:192px; }}
.panel-title {{ position:absolute; top:9px; left:10px; z-index:2; font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:rgba(75,85,99,.72); }}
#axisViewer,#cellViewer {{ position:absolute; inset:0; }}
.platform-shadow {{ position:absolute; left:50%; bottom:60px; width:42%; height:20px; transform:translateX(-50%); background:radial-gradient(ellipse at center,rgba(75,85,99,.16),rgba(120,130,145,.08) 50%,transparent 72%); filter:blur(2px); pointer-events:none; z-index:3; }}
.platform-line {{ position:absolute; left:30%; right:30%; bottom:74px; height:1px; background:linear-gradient(90deg,transparent,rgba(75,85,99,.40),transparent); pointer-events:none; z-index:3; }}
.info-bottom {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border-top:1px solid rgba(30,35,45,.18); background:linear-gradient(180deg,#fff,#eef1f5); }}
.info-card {{ padding:15px 14px; border-right:1px solid rgba(30,35,45,.10); min-width:0; }}
.info-card:last-child {{ border-right:none; }}
.info-label {{ font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:rgba(75,85,99,.68); margin-bottom:9px; }}
.info-value {{ font-size:14px; line-height:1.4; font-weight:720; color:#111827; word-break:break-word; }}
#msg {{ position:absolute; top:70px; left:22px; z-index:20; color:#7f1d1d; background:#fff; border:1px solid rgba(127,29,29,.22); padding:7px 10px; display:none; }}
</style>
</head>
<body>
<div class="studio">
  <div class="toolbar">
    <div class="controls">
      <button type="button" onclick="resetView()">Reset</button>
      <select id="styleMode" onchange="renderCurrent()">
        <option value="scientific">Scientific</option>
        <option value="dense">Dense Cell</option>
        <option value="spacefill">Space Filling</option>
        <option value="minimal">Minimal</option>
      </select>
      <select id="bgMode" onchange="renderCurrent()">
        <option value="soft">Soft White</option>
        <option value="gray">Instrument Gray</option>
        <option value="paper">Paper White</option>
      </select>
      <select id="cellMode" onchange="renderCurrent()">
        <option value="1">Single Cell</option>
        <option value="2">2 × 2 × 2</option>
        <option value="3">3 × 3 × 3</option>
      </select>
      <label class="check"><input id="spinToggle" type="checkbox" checked onchange="toggleSpin()" /> Spin</label>
      <button type="button" onclick="downloadPNG()">PNG</button>
      <button type="button" onclick="downloadJPG()">JPG</button>
      <button type="button" onclick="downloadHTML()">3D HTML</button>
    </div>
  </div>
  <section class="stage">
    <div id="msg"></div>
    <div id="{viewer_id}" class="viewer"></div>
    <div class="ruler-top"></div><div class="ruler-left"></div>
    <div class="inspector"><div class="inspector-head">Selected Atom</div><div id="atomInfo" class="inspector-body">Move cursor over an atom.</div></div>
    <div class="mini-cell-panel"><div class="panel-title">Unit Cell</div><div id="cellViewer"></div></div>
    <div class="platform-shadow"></div><div class="platform-line"></div>
  </section>
  <section class="info-bottom">
    <div class="info-card"><div class="info-label">Space Group</div><div class="info-value" id="sgText">—</div></div>
    <div class="info-card"><div class="info-label">Crystal System</div><div class="info-value" id="crystalText">—</div></div>
    <div class="info-card"><div class="info-label">Sites</div><div class="info-value" id="sitesText">—</div></div>
    <div class="info-card"><div class="info-label">Volume</div><div class="info-value" id="volumeText">—</div></div>
    <div class="info-card"><div class="info-label">Density</div><div class="info-value" id="densityText">—</div></div>
  </section>
</div>
<script>
const CIF_TEXT = {cif_js};
const FORMULA = {formula_js};
const ELEMENTS = {element_js};
const PALETTE = ['#111827','#2f3742','#4b5563','#64748b','#8a94a3','#b8c0cc','#1f4e79','#3f6f9f','#d7dce3'];
let viewer = null, model = null, cellViewer = null;
const info = document.getElementById('atomInfo');
const formulaNode = document.getElementById('formulaText');
if (formulaNode) formulaNode.textContent = FORMULA;

document.getElementById('sgText').textContent = {json.dumps(build_basic_parameters(structure)[3]['value'])};
document.getElementById('crystalText').textContent = {json.dumps(build_basic_parameters(structure)[4]['value'])};
document.getElementById('sitesText').textContent = {json.dumps(str(len(structure)))};
document.getElementById('volumeText').textContent = {json.dumps(f'{structure.lattice.volume:.4f} Å³')};
document.getElementById('densityText').textContent = {json.dumps(f'{structure.density:.4f} g/cm³')};

function bgColor() {{
  const v = document.getElementById('bgMode').value;
  if (v === 'gray') return '#eceff3';
  if (v === 'paper') return '#ffffff';
  return '#f7f8fa';
}}
function colorForElement(elem, i) {{
  const e = String(elem || '').toUpperCase();
  if (e === 'H') return '#d7dce3';
  if (e === 'O' || e === 'N') return '#64748b';
  if (e === 'C') return '#2f3742';
  return PALETTE[i % PALETTE.length];
}}
function styleFor(mode, color) {{
  const c = color || '#4b5563';
  if (mode === 'spacefill') return {{ sphere: {{ scale: 0.78, color: c }}}};
  if (mode === 'minimal') return {{ stick: {{ radius: 0.13, color: c }}, sphere: {{ scale: 0.13, color: c }}}};
  if (mode === 'dense') return {{ sphere: {{ scale: 0.25, color: c }}, stick: {{ radius: 0.08, color: c }}}};
  return {{ sphere: {{ scale: {sphere_scale}, color: c }}, stick: {{ radius: {stick_radius}, color: c }}}};
}}
function applyScientificColors(mode) {{
  viewer.setStyle({{}}, styleFor(mode, '#4b5563'));
  ELEMENTS.forEach((elem, i) => {{
    viewer.setStyle({{elem: elem}}, styleFor(mode, colorForElement(elem, i)));
  }});
}}
function replication() {{
  const n = Number(document.getElementById('cellMode').value || 1);
  return [n, n, n];
}}
function renderCurrent() {{
  try {{
    if (!window.$3Dmol) throw new Error('3Dmol unavailable');
    const mode = document.getElementById('styleMode').value;
    if (!viewer) viewer = $3Dmol.createViewer('{viewer_id}', {{ backgroundColor: bgColor() }});
    viewer.setBackgroundColor(bgColor());
    viewer.removeAllModels();
    model = viewer.addModel(CIF_TEXT, 'cif');
    applyScientificColors(mode);
    viewer.addUnitCell(model);
    const r = replication();
    try {{ viewer.replicateUnitCell(r[0], r[1], r[2], model, true, false); }} catch(e) {{}}
    try {{
      viewer.setHoverable({{}}, true, function(atom) {{
        if (!atom) return;
        const elem = atom.elem || atom.element || atom.atom || 'Atom';
        const serial = atom.serial || atom.index || '—';
        const x = Number(atom.x || 0).toFixed(3), y = Number(atom.y || 0).toFixed(3), z = Number(atom.z || 0).toFixed(3);
        info.innerHTML = `<b>Element:</b> ${{elem}}<br><b>Atom ID:</b> ${{serial}}<br><b>Cartesian / Å:</b> ${{x}}, ${{y}}, ${{z}}`;
      }}, function() {{}});
    }} catch(e) {{}}
    viewer.zoomTo(); viewer.render();
    toggleSpin();
    renderInsets();
  }} catch (e) {{
    const msg=document.getElementById('msg'); msg.textContent='Structure rendering failed.'; msg.style.display='block';
  }}
}}
function renderInsets() {{
  try {{
    if (!cellViewer) cellViewer = $3Dmol.createViewer('cellViewer', {{ backgroundColor: 'rgba(255,255,255,0)' }});
    cellViewer.removeAllModels();
    const cm=cellViewer.addModel(CIF_TEXT,'cif');
    cellViewer.setStyle({{}},{{sphere:{{scale:.16,color:'#64748b'}},stick:{{radius:.045,color:'#4b5563'}}}});
    cellViewer.addUnitCell(cm); cellViewer.zoomTo(); cellViewer.zoom(0.8); cellViewer.render();
  }} catch(e) {{}}
}}
function toggleSpin() {{ if (!viewer) return; viewer.spin(document.getElementById('spinToggle').checked ? 'y' : false, 0.45); viewer.render(); }}
function resetView() {{ if (viewer) {{ viewer.zoomTo(); viewer.render(); }} }}
function downloadCIF() {{
  const blob = new Blob([CIF_TEXT], {{type:'chemical/x-cif;charset=utf-8'}});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = FORMULA.replace(/[^A-Za-z0-9_]+/g,'_') + '.cif'; a.click(); URL.revokeObjectURL(a.href);
}}
function downloadPNG() {{ try {{ const uri = viewer.pngURI(); const a=document.createElement('a'); a.href=uri; a.download=FORMULA.replace(/[^A-Za-z0-9_]+/g,'_')+'.png'; a.click(); }} catch(e) {{}} }}
function downloadJPG() {{
  try {{
    const png = viewer.pngURI();
    const img = new Image();
    img.onload = function() {{
      const canvas = document.createElement('canvas');
      canvas.width = img.width; canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = bgColor();
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      const uri = canvas.toDataURL('image/jpeg', 0.92);
      const a = document.createElement('a');
      a.href = uri;
      a.download = FORMULA.replace(/[^A-Za-z0-9_]+/g,'_') + '.jpg';
      a.click();
    }};
    img.src = png;
  }} catch(e) {{}}
}}

function downloadHTML() {{
  try {{
    const doc = '<!doctype html>\\n' + document.documentElement.outerHTML;
    const blob = new Blob([doc], {{type:'text/html;charset=utf-8'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = FORMULA.replace(/[^A-Za-z0-9_]+/g,'_') + '_3d_viewer.html';
    a.click();
    URL.revokeObjectURL(a.href);
  }} catch(e) {{}}
}}
renderCurrent();
</script>
</body>
</html>
"""
