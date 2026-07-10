const PROPERTIES = [
  { key: "band_gap", label: "带隙", unit: "eV", defaultTarget: 1.5, weight: 1.0 },
  { key: "bulk_modulus", label: "体模量", unit: "GPa", defaultTarget: 120.0, weight: 1.0 },
  { key: "larsen_score_2d", label: "Larsen 二维分数", unit: "", defaultTarget: 0.50, weight: 1.0 },
  { key: "dielectric_constant", label: "介电常数", unit: "εx/εy/εz", defaultTarget: 10.0, weight: 1.0 },
  { key: "mag_density", label: "磁密度", unit: "μB/Å³", defaultTarget: 0.20, weight: 1.0 },
  { key: "cauchy_stress", label: "柯西应力", unit: "GPa", defaultTarget: 0.0, weight: 1.0 },
];

const state = {
  candidates: [],
  activeCandidateId: null,
  timer: null,
  startedAt: null,
  predictionTimer: null,
  predictionStartedAt: null,
  predictionSourceCandidateId: null,
  predictionLoadedCif: "",
};

const $ = (id) => document.getElementById(id);

function propertyMeta(key) {
  return PROPERTIES.find(p => p.key === key) || { label: key, unit: "" };
}

function fmt(x, digits = 4) {
  if (x === null || x === undefined || x === "" || Number.isNaN(Number(x))) return "—";
  const n = Number(x);
  if (Math.abs(n) >= 100) return n.toFixed(2);
  if (Math.abs(n) >= 1) return n.toFixed(digits);
  return n.toPrecision(4);
}

function initPropertyInputs() {
  const grid = $("propertyGrid");
  grid.innerHTML = "";
  for (const p of PROPERTIES) {
    const card = document.createElement("div");
    card.className = "property-card";
    card.innerHTML = `
      <label><span>${p.label}</span><small>${p.unit || "dimensionless"}</small></label>
      <input id="target_${p.key}" type="number" step="any" value="${p.defaultTarget}" placeholder="目标值" />
      <div class="weight-line">
        <span>权重</span>
        <input id="weight_${p.key}" type="range" min="0" max="2" step="0.05" value="${p.weight}" />
        <strong id="wtext_${p.key}">${p.weight.toFixed(2)}</strong>
      </div>
    `;
    grid.appendChild(card);
    setTimeout(() => {
      const slider = $(`weight_${p.key}`);
      const label = $(`wtext_${p.key}`);
      slider.addEventListener("input", () => label.textContent = Number(slider.value).toFixed(2));
    });
  }
}

function collectPayload() {
  const targets = {};
  const weights = {};
  for (const p of PROPERTIES) {
    const targetValue = $(`target_${p.key}`).value;
    const weightValue = Number($(`weight_${p.key}`).value);
    const target = targetValue === "" ? null : Number(targetValue);
    targets[p.key] = Number.isFinite(target) ? target : null;
    weights[p.key] = targets[p.key] === null ? 0 : weightValue;
  }
  return {
    targets,
    weights,
    topk: Math.max(1, Math.min(20, Number($("topkInput").value || 5))),
    function_text: $("functionText").value || "",
  };
}

function fillParsed(parsed) {
  for (const p of PROPERTIES) {
    const v = parsed.targets?.[p.key];
    const w = parsed.weights?.[p.key];
    if (v !== null && v !== undefined) $(`target_${p.key}`).value = v;
    if (w !== null && w !== undefined) {
      $(`weight_${p.key}`).value = w;
      $(`wtext_${p.key}`).textContent = Number(w).toFixed(2);
    }
  }
}

async function parseFunctionText() {
  const text = $("functionText").value.trim();
  if (!text) {
    setStatus("请先输入功能描述。");
    return;
  }
  setStatus("正在解析功能描述...");
  try {
    const res = await fetch("/api/parse-function", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error("parse failed");
    const data = await res.json();
    fillParsed(data);
    setStatus("已转换为目标性质参数。");
  } catch {
    setStatus("解析失败，请手动设置性质参数。");
  }
}

function setStatus(text) {
  $("runStatus").textContent = text;
}

function startLoading() {
  $("loadingBox").classList.remove("hidden");
  state.startedAt = performance.now();
  $("elapsedTime").textContent = "0.0";
  state.timer = setInterval(() => {
    const sec = (performance.now() - state.startedAt) / 1000;
    $("elapsedTime").textContent = sec.toFixed(1);
  }, 100);
}

function stopLoading() {
  $("loadingBox").classList.add("hidden");
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

async function generateMaterials() {
  const payload = collectPayload();
  const hasActiveTarget = Object.keys(payload.targets).some(k => payload.targets[k] !== null && Number(payload.weights[k]) > 0);
  if (!hasActiveTarget && !payload.function_text.trim()) {
    setStatus("请至少填写一个目标性质，或输入功能描述后再生成。");
    return;
  }
  startLoading();
  setStatus("运行中...");
  const clientStart = performance.now();
  try {
    const res = await fetch("/api/submit-design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error("generation failed");
    }
    const data = await res.json();
    state.candidates = data.candidates || [];
    state.activeCandidateId = state.candidates[0]?.candidate_id || null;
    renderCandidates();
    const totalClient = (performance.now() - clientStart) / 1000;
    const t = data.timing || {};
    $("timingText").textContent = `生成 ${fmt(t.retrieval_seconds, 2)} s · 渲染 ${fmt(t.render_seconds, 2)} s · 总计 ${fmt(t.total_seconds, 2)} s · 页面等待 ${totalClient.toFixed(2)} s`;
    $("lastTimeView").textContent = `${fmt(t.total_seconds, 2)}s`;
    $("candidateCountView").textContent = state.candidates.length;
    setStatus("生成完成");
    location.hash = "home";
  } catch {
    setStatus("生成失败");
  } finally {
    stopLoading();
  }
}

function renderCandidates() {
  const box = $("candidateList");
  box.classList.remove("empty-state");
  if (!state.candidates.length) {
    box.classList.add("empty-state");
    box.innerHTML = `<div class="empty-card">暂无候选结构。请先设置性质并点击“生成结构”。</div>`;
    return;
  }
  box.innerHTML = "";
  for (const c of state.candidates) {
    const card = document.createElement("article");
    card.className = "candidate-card";
    const imgs = (c.image_urls || []).slice(0, 3).map(url => `<div class="thumb"><img src="${url}" alt="view" loading="lazy" /></div>`).join("");
    const placeholders = [0,1,2].slice((c.image_urls || []).length).map(() => `<div class="thumb">三视图</div>`).join("");
    const props = (c.property_rows || []).map(r => `<span class="prop-pill">${r.name}: ${r.value}${r.unit ? " " + r.unit : ""}</span>`).join("");
    const basics = (c.basic_parameters || []).slice(0, 6).map(r => `<div title="${r.name}: ${r.value}">${r.name}: ${r.value}</div>`).join("");
    card.innerHTML = `
      <div class="thumbnail-triplet" data-open="structure" data-id="${c.candidate_id}">${imgs}${placeholders}</div>
      <div class="candidate-main">
        <div class="candidate-title-row">
          <div>
            <div class="candidate-title">${c.title}</div>
            <div class="candidate-id">候选结构 #${c.rank}</div>
          </div>
          <div class="rank-pill">#${c.rank}</div>
        </div>
        <div class="property-pills">${props}</div>
        <div class="basic-mini">${basics}</div>
        <div class="candidate-actions">
          <button class="action-btn" data-open="structure" data-id="${c.candidate_id}">晶体微观结构</button>
          <button class="action-btn" data-open="properties" data-id="${c.candidate_id}">晶体性质</button>
          <button class="action-btn" data-open="wyckoff" data-id="${c.candidate_id}">Wyckoff 位点渲染</button>
          <button class="action-btn prediction-action-btn" data-open="prediction" data-id="${c.candidate_id}">性质预测</button>
        </div>
      </div>
    `;
    box.appendChild(card);
  }
}

function showPage(name) {
  for (const el of document.querySelectorAll(".page")) el.classList.remove("page-active");
  const page = $(`page${name[0].toUpperCase()}${name.slice(1)}`);
  if (page) page.classList.add("page-active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderKVTable(el, rows) {
  el.innerHTML = (rows || []).map(r => `
    <div class="kv-row">
      <div class="kv-key">${r.name}</div>
      <div class="kv-value">${r.value}${r.unit ? " " + r.unit : ""}</div>
    </div>
  `).join("");
}

async function openStructure(id) {
  state.activeCandidateId = id;
  showPage("structure");
  $("structureTitle").textContent = "晶体微观结构";
  $("structureSubtitle").textContent = "正在加载...";
  $("viewerFrame").srcdoc = "";
  $("cifText").textContent = "";
  try {
    const res = await fetch(`/api/candidates/${id}`);
    if (!res.ok) throw new Error("failed");
    const data = await res.json();
    $("structureTitle").textContent = data.formula || data.title;
    $("structureSubtitle").textContent = "";
    $("viewerFrame").srcdoc = data.viewer_html || "";
    $("cifText").textContent = data.cif_text || "";
    renderKVTable($("structureBasicTable"), data.basic_parameters || []);
    const dl = $("downloadCifBtn");
    if (dl) {
      dl.href = `/api/candidates/${id}/cif`;
      dl.download = `${(data.formula || data.title || "candidate_structure").replace(/[^A-Za-z0-9_\-]+/g, "_")}.cif`;
    }
  } catch {
    $("structureSubtitle").textContent = "加载失败";
  }
}

async function openProperties(id) {
  state.activeCandidateId = id;
  showPage("properties");
  $("propTitle").textContent = "性质分析";
  $("propSubtitle").textContent = "正在加载...";
  try {
    const res = await fetch(`/api/candidates/${id}/properties`);
    if (!res.ok) throw new Error("failed");
    const data = await res.json();
    $("propTitle").textContent = data.formula || data.title;
    $("propSubtitle").textContent = "";
    renderKVTable($("propertyTable"), data.property_rows || []);
    renderKVTable($("propertyBasicTable"), data.basic_parameters || []);
    const plots = data.property_plots || [];
    $("plotGrid").innerHTML = plots.map(p => {
      const stats = p.stats || {};
      const meta = p.url
        ? `<img src="${p.url}?t=${Date.now()}" alt="${p.title}" loading="lazy" />`
        : `<div class="plot-placeholder-inner">暂无图像</div>`;
      const sample = stats.sample === null || stats.sample === undefined ? "—" : fmt(stats.sample, 4);
      const percentile = stats.percentile === null || stats.percentile === undefined ? "—" : `P${Number(stats.percentile).toFixed(1)}`;
      return `
        <article class="plot-card">
          <div class="plot-card-head">
            <div>
              <strong>${p.title}</strong>
              <span>${p.note || ""}</span>
            </div>
            <div class="plot-badge">${percentile}</div>
          </div>
          <div class="plot-image-wrap">${meta}</div>
          <div class="plot-stat-row">
            <span>候选值 ${sample}${p.unit ? " " + p.unit : ""}</span>
            <span>样本数 ${stats.count || "—"}</span>
            <span>均值 ${stats.mean === undefined ? "—" : fmt(stats.mean, 4)}</span>
          </div>
        </article>
      `;
    }).join("");
  } catch {
    $("propSubtitle").textContent = "加载失败";
  }
}

function renderViewTriplet(el, urls) {
  el.innerHTML = [0,1,2].map(i => {
    const url = (urls || [])[i];
    return `<div class="view-img">${url ? `<img src="${url}" alt="view ${i+1}" />` : "图像不可用"}</div>`;
  }).join("");
}

async function openWyckoff(id) {
  state.activeCandidateId = id;
  showPage("wyckoff");
  $("wyckoffTitle").textContent = "Wyckoff 位点渲染";
  $("wyckoffSubtitle").textContent = "正在计算并渲染位点...";
  $("wyckoffFullViews").innerHTML = `<div class="empty-card">正在生成图片...</div>`;
  $("wyckoffTable").innerHTML = "";
  $("wyckoffGroups").innerHTML = "";
  try {
    const res = await fetch(`/api/candidates/${id}/wyckoff`);
    if (!res.ok) throw new Error("failed");
    const data = await res.json();
    $("wyckoffTitle").textContent = data.formula || data.title;
    $("wyckoffSubtitle").textContent = `共 ${(data.groups || []).length} 个 Wyckoff group`;
    renderViewTriplet($("wyckoffFullViews"), data.full_image_urls || []);

    const rows = (data.groups || []).map(g => `
      <tr>
        <td>${g.gid}</td>
        <td>${g.element}</td>
        <td>${g.multiplicity}${g.wyckoff}</td>
        <td>[${(g.representative_frac || []).map(x => Number(x).toFixed(6)).join(", ")}]</td>
        <td>${(g.indices || []).join(", ")}</td>
      </tr>
    `).join("");
    $("wyckoffTable").innerHTML = `
      <table>
        <thead><tr><th>Group</th><th>元素</th><th>Wyckoff</th><th>代表分数坐标</th><th>位点索引</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;

    $("wyckoffGroups").innerHTML = (data.groups || []).map(g => `
      <article class="wyckoff-group-card">
        <h3>Group ${g.gid}: ${g.element} ${g.multiplicity}${g.wyckoff}</h3>
        <div class="view-triplet">
          ${[0,1,2].map(i => {
            const url = (g.image_urls || [])[i];
            return `<div class="view-img">${url ? `<img src="${url}" alt="group view" />` : "图像不可用"}</div>`;
          }).join("")}
        </div>
      </article>
    `).join("");
  } catch {
    $("wyckoffSubtitle").textContent = "生成失败";
    $("wyckoffFullViews").innerHTML = `<div class="empty-card">生成失败</div>`;
  }
}


function clampPercent(value, maxValue) {
  const n = Number(value);
  if (!Number.isFinite(n) || maxValue <= 0) return 0;
  return Math.max(0, Math.min(100, (n / maxValue) * 100));
}

function predictionNumber(value, digits = 4) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) < 0.001 && n !== 0) return n.toExponential(3);
  return n.toFixed(digits).replace(/\.?0+$/, "");
}

function setPredictionStatus(text, mode = "idle") {
  const el = $("predictionStatus");
  if (!el) return;
  el.textContent = text;
  el.dataset.mode = mode;
}

function startPredictionLoading() {
  $("predictionEmpty").classList.add("hidden");
  $("predictionResult").classList.add("hidden");
  $("predictionLoading").classList.remove("hidden");
  state.predictionStartedAt = performance.now();
  $("predictionElapsed").textContent = "0.0";
  state.predictionTimer = setInterval(() => {
    const seconds = (performance.now() - state.predictionStartedAt) / 1000;
    $("predictionElapsed").textContent = seconds.toFixed(1);
  }, 100);
}

function stopPredictionLoading() {
  $("predictionLoading").classList.add("hidden");
  if (state.predictionTimer) clearInterval(state.predictionTimer);
  state.predictionTimer = null;
}

function clearPredictionWorkspace() {
  state.predictionSourceCandidateId = null;
  state.predictionLoadedCif = "";
  $("predictionCifText").value = "";
  $("predictionFileInput").value = "";
  $("predictionSourceName").textContent = "未选择结构";
  $("predictionViewerFrame").srcdoc = "";
  $("predictionResult").classList.add("hidden");
  $("predictionLoading").classList.add("hidden");
  $("predictionEmpty").classList.remove("hidden");
  setPredictionStatus("等待晶体结构输入");
}

async function updatePredictionEngineBadge() {
  const badge = $("predictionEngineBadge");
  if (!badge) return;
  try {
    const res = await fetch("/api/property-predictor/status");
    if (!res.ok) throw new Error("status failed");
    const data = await res.json();
    const labels = {
      idle: "计算引擎 · 待机",
      loading: "计算引擎 · 加载中",
      ready: `计算引擎 · ${String(data.device || "CPU").toUpperCase()} 就绪`,
      error: "计算引擎 · 异常",
    };
    badge.textContent = labels[data.status] || "计算引擎 · 待机";
    badge.dataset.status = data.status || "idle";
  } catch {
    badge.textContent = "计算引擎 · 状态未知";
    badge.dataset.status = "error";
  }
}

async function loadCandidateIntoPrediction(id, autoRun = false) {
  if (!id) return;
  showPage("prediction");
  setPredictionStatus("正在读取候选结构...", "running");
  try {
    const res = await fetch(`/api/candidates/${id}`);
    if (!res.ok) throw new Error("candidate failed");
    const data = await res.json();
    const cif = data.cif_text || "";
    state.activeCandidateId = id;
    state.predictionSourceCandidateId = id;
    state.predictionLoadedCif = cif;
    $("predictionCifText").value = cif;
    $("predictionSourceName").textContent = data.formula || data.title || "当前候选";
    $("predictionViewerFrame").srcdoc = data.viewer_html || "";
    setPredictionStatus(autoRun ? "结构已载入，正在启动预测..." : "候选结构已载入");
    if (autoRun) await runPropertyPrediction({ candidateId: id });
  } catch {
    setPredictionStatus("候选结构读取失败", "error");
  }
}

function renderPredictionResult(data) {
  $("predictionFormula").textContent = data.formula || "未知结构";
  $("predictionMeta").textContent = `${data.n_sites ?? "—"} 个原子位点 · 晶胞体积 ${predictionNumber(data.volume_A3, 3)} Å³ · ${data.engine?.device || "CPU"}`;
  $("predictionMagDensity").textContent = predictionNumber(data.magnetic_moment_density_muB_A3, 6);
  $("predictionBandGap").textContent = predictionNumber(data.band_gap_eV, 4);
  $("predictionDielectric").textContent = predictionNumber(data.max_static_dielectric, 4);
  $("predictionMagLabel").textContent = data.interpretation?.magnetic || "—";
  $("predictionGapLabel").textContent = data.interpretation?.band_gap || "—";
  $("predictionDielectricLabel").textContent = data.interpretation?.dielectric || "—";
  $("predictionMagBar").style.width = `${clampPercent(data.magnetic_moment_density_muB_A3, 0.30)}%`;
  $("predictionGapBar").style.width = `${clampPercent(data.band_gap_eV, 6.0)}%`;
  $("predictionDielectricBar").style.width = `${clampPercent(data.max_static_dielectric, 100)}%`;
  $("predictionViewerFrame").srcdoc = data.viewer_html || "";

  const summaryRows = [
    { name: "化学式", value: data.formula || "—" },
    { name: "原子位点", value: data.n_sites ?? "—" },
    { name: "晶胞体积", value: `${predictionNumber(data.volume_A3, 4)} Å³` },
    { name: "局域绝对磁矩", value: `${predictionNumber(data.local_absolute_moment_muB, 5)} μB` },
    { name: "平均位点磁矩", value: `${predictionNumber(data.mean_site_moment_muB, 5)} μB` },
    { name: "最大位点磁矩", value: `${predictionNumber(data.max_site_moment_muB, 5)} μB` },
  ];
  $("predictionBasicTable").innerHTML = summaryRows.map(row => `
    <div><span>${row.name}</span><strong>${row.value}</strong></div>
  `).join("");

  const moments = Array.isArray(data.site_moments_muB) ? data.site_moments_muB : [];
  const shown = moments.slice(0, 48);
  const maxMoment = Math.max(0.001, ...shown.map(x => Number(x) || 0));
  $("predictionSiteCount").textContent = moments.length > shown.length ? `显示前 ${shown.length} / ${moments.length} 个位点` : `${moments.length} 个位点`;
  $("predictionSiteMoments").innerHTML = shown.length ? shown.map((value, index) => `
    <div class="site-moment-row">
      <span>Site ${index + 1}</span>
      <div><i style="width:${clampPercent(value, maxMoment)}%"></i></div>
      <strong>${predictionNumber(value, 5)} μB</strong>
    </div>
  `).join("") : `<div class="empty-card">无位点磁矩数据</div>`;

  $("predictionNotices").innerHTML = (data.notices || []).map((text, index) => `
    <div><span>${String(index + 1).padStart(2, "0")}</span><p>${text}</p></div>
  `).join("");

  $("predictionEmpty").classList.add("hidden");
  $("predictionLoading").classList.add("hidden");
  $("predictionResult").classList.remove("hidden");
}

async function runPropertyPrediction(options = {}) {
  const cif = $("predictionCifText").value.trim();
  if (!cif) {
    setPredictionStatus("请先载入或粘贴 CIF 结构", "error");
    return;
  }

  startPredictionLoading();
  setPredictionStatus("正在推演晶体性质...", "running");
  await updatePredictionEngineBadge();
  try {
    const canUseCandidateEndpoint = options.candidateId && cif === state.predictionLoadedCif;
    const endpoint = canUseCandidateEndpoint
      ? `/api/candidates/${options.candidateId}/predict-properties`
      : "/api/property-predictor/predict";
    const fetchOptions = canUseCandidateEndpoint ? { method: "POST" } : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cif,
        source_name: $("predictionSourceName").textContent || "自定义 CIF",
      }),
    };
    const res = await fetch(endpoint, fetchOptions);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "预测失败");
    renderPredictionResult(data);
    setPredictionStatus("预测完成", "success");
  } catch (error) {
    $("predictionEmpty").classList.remove("hidden");
    setPredictionStatus(error?.message || "性质预测失败", "error");
  } finally {
    stopPredictionLoading();
    await updatePredictionEngineBadge();
  }
}

async function openPrediction(id = null) {
  showPage("prediction");
  await updatePredictionEngineBadge();
  if (id) {
    await loadCandidateIntoPrediction(id, true);
  }
}

function route() {
  const hash = (location.hash || "#home").replace(/^#/, "");
  const [page, id] = hash.split("/");
  if (page === "structure" && id) return openStructure(id);
  if (page === "properties" && id) return openProperties(id);
  if (page === "wyckoff" && id) return openWyckoff(id);
  if (page === "prediction") return openPrediction(id || null);
  showPage("home");
}

function clearInputs() {
  for (const p of PROPERTIES) {
    $(`target_${p.key}`).value = "";
    $(`weight_${p.key}`).value = String(p.weight);
    $(`wtext_${p.key}`).textContent = Number(p.weight).toFixed(2);
  }
  $("functionText").value = "";
  setStatus("已清空");
}

function goToActive(kind) {
  const id = state.activeCandidateId || state.candidates[0]?.candidate_id;
  if (!id) {
    location.hash = "home";
    return;
  }
  location.hash = `${kind}/${id}`;
}

function bindEvents() {
  $("parseBtn").addEventListener("click", parseFunctionText);
  $("generateBtn").addEventListener("click", generateMaterials);
  $("clearBtn").addEventListener("click", clearInputs);
  $("backHomeBtn").addEventListener("click", () => location.hash = "home");
  $("structurePredictBtn").addEventListener("click", () => {
    const id = state.activeCandidateId;
    location.hash = id ? `prediction/${id}` : "prediction";
  });
  $("predictionRunBtn").addEventListener("click", () => runPropertyPrediction({
    candidateId: state.predictionSourceCandidateId,
  }));
  $("predictionClearBtn").addEventListener("click", clearPredictionWorkspace);
  $("predictionUseCandidateBtn").addEventListener("click", () => {
    const id = state.activeCandidateId || state.candidates[0]?.candidate_id;
    if (!id) {
      setPredictionStatus("当前没有可用候选结构", "error");
      return;
    }
    loadCandidateIntoPrediction(id, false);
  });
  $("predictionFileInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      state.predictionSourceCandidateId = null;
      state.predictionLoadedCif = text;
      $("predictionCifText").value = text;
      $("predictionSourceName").textContent = file.name;
      setPredictionStatus("CIF 文件已载入");
    } catch {
      setPredictionStatus("CIF 文件读取失败", "error");
    }
  });
  $("predictionCifText").addEventListener("input", () => {
    if ($("predictionCifText").value !== state.predictionLoadedCif) {
      state.predictionSourceCandidateId = null;
      $("predictionSourceName").textContent = "自定义 CIF";
    }
  });
  const sideRoutes = {
    sideOpenStructureStructure: "structure",
    sideOpenPropertiesStructure: "properties",
    sideOpenWyckoffStructure: "wyckoff",
    sideOpenStructureProperties: "structure",
    sideOpenPropertiesProperties: "properties",
    sideOpenWyckoffProperties: "wyckoff",
    sideOpenStructureWyckoff: "structure",
    sideOpenPropertiesWyckoff: "properties",
    sideOpenWyckoffWyckoff: "wyckoff",
    sideOpenPredictionStructure: "prediction",
    sideOpenPredictionProperties: "prediction",
    sideOpenPredictionWyckoff: "prediction",
  };
  for (const [id, kind] of Object.entries(sideRoutes)) {
    const btn = $(id);
    if (btn) btn.addEventListener("click", () => goToActive(kind));
  }

  document.body.addEventListener("click", (e) => {
    const routeTarget = e.target.closest("[data-route]");
    if (routeTarget) {
      location.hash = routeTarget.dataset.route;
      return;
    }
    const openTarget = e.target.closest("[data-open]");
    if (openTarget) {
      const id = openTarget.dataset.id;
      const kind = openTarget.dataset.open;
      location.hash = `${kind}/${id}`;
    }
  });
  window.addEventListener("hashchange", route);
  window.addEventListener("scroll", () => {
    const bar = document.querySelector(".topbar");
    if (!bar) return;
    bar.classList.toggle("scrolled", window.scrollY > 18);
  }, { passive: true });
}

async function loadHeroCrystal() {
  const frame = $("heroCrystalFrame");
  if (!frame) return;
  try {
    const res = await fetch(`/api/hero-crystal?t=${Date.now()}`);
    if (!res.ok) throw new Error("hero failed");
    const data = await res.json();
    frame.srcdoc = data.viewer_html || "";
  } catch {
    frame.srcdoc = "";
  }
}

initPropertyInputs();
bindEvents();
loadHeroCrystal();
updatePredictionEngineBadge();
route();
