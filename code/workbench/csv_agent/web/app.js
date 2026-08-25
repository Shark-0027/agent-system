/* AI 数据分析 Agent 工作台前端逻辑（单页 SPA：idle / running / done） */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const TOOL_LABEL = {
    csv_load: "加载数据", data_summary: "数据概览", data_clean: "数据清洗",
    feature_engineer: "特征工程", eda_plot: "可视化", model_suggest: "模型建议",
    model_train: "模型训练", model_classify: "模型分类", report_generate: "生成报告",
    corr_analysis: "相关性热图", hypo_test: "假设检验", regression_fit: "回归拟合",
    time_series_feat: "时间序列", cluster_profile: "聚类分析", anomaly_detect: "离群点检测",
    dist_fit: "分布拟合", pca_decompose: "主成分分析", data_quality: "数据质量体检",
    nl_filter: "智能查数", nl_agg: "分组聚合", nl_insight: "智能洞察",
    missing_pattern: "缺失模式分析", feature_select: "特征选择",
    time_series_forecast: "时序预测", ab_test: "A/B实验",
    sample_size_calc: "样本量计算", table_join: "多表关联",
  };

  const TOOL_GROUP = {
    csv_load: "load", data_summary: "load", data_quality: "hygiene", data_clean: "clean",
    feature_engineer: "feature", eda_plot: "visual", model_suggest: "model", model_train: "model",
    model_classify: "model", report_generate: "report", corr_analysis: "stats", hypo_test: "stats",
    regression_fit: "stats", time_series_feat: "stats", cluster_profile: "stats", anomaly_detect: "stats",
    dist_fit: "stats", pca_decompose: "stats", nl_filter: "nl", nl_agg: "nl", nl_insight: "nl",
    missing_pattern: "hygiene", feature_select: "feature",
    time_series_forecast: "stats", ab_test: "stats",
    sample_size_calc: "stats", table_join: "clean",
  };

  const GROUP_NAME = {
    load: "加载与概览", clean: "数据清洗", feature: "特征工程", stats: "统计分析",
    visual: "可视化", model: "建模", report: "报告", nl: "自然语言", hygiene: "质量体检",
  };

  // 工具参数配置表
  const TOOL_PARAMS = {
    data_clean: [
      { key: "fill", label: "缺失填充", type: "select", options: ["median", "mean"], default: "median" },
      { key: "strategy", label: "填充策略", type: "select", options: ["simple", "knn", "group"], default: "simple" },
      { key: "outlier_method", label: "异常值处理", type: "select", options: ["iqr", "zscore", "isoforest", "mark"], default: "iqr" },
      { key: "group_col", label: "分组列(group策略用)", type: "input", default: "" },
    ],
    hypo_test: [
      { key: "test_type", label: "检验类型", type: "select",
        options: ["normality", "ttest", "anova", "chi2", "wilcoxon", "mannwhitney", "ks"], default: "normality" },
      { key: "col", label: "检验列", type: "input", default: "" },
      { key: "group", label: "分组列", type: "input", default: "" },
      { key: "col2", label: "第二列(卡方用)", type: "input", default: "" },
    ],
    model_train: [
      { key: "target", label: "目标列", type: "input", default: "" },
      { key: "models", label: "模型", type: "input", default: "lr,rf" },
      { key: "cv_folds", label: "CV折数", type: "input", default: "0" },
      { key: "tune", label: "超参调优", type: "checkbox", default: false },
    ],
    feature_engineer: [
      { key: "encode", label: "分类编码", type: "checkbox", default: true },
      { key: "scale", label: "标准化", type: "checkbox", default: true },
      { key: "interaction", label: "交互特征", type: "checkbox", default: false },
      { key: "binning", label: "分箱", type: "checkbox", default: false },
      { key: "datetime_feat", label: "日期特征", type: "checkbox", default: false },
    ],
    feature_select: [
      { key: "method", label: "选择方法", type: "select", options: ["vif", "mutual_info", "rfe"], default: "vif" },
      { key: "target", label: "目标列", type: "input", default: "" },
    ],
    time_series_forecast: [
      { key: "method", label: "预测方法", type: "select", options: ["arima", "exponential", "naive"], default: "arima" },
      { key: "date", label: "日期列", type: "input", default: "" },
      { key: "col", label: "数值列", type: "input", default: "" },
      { key: "steps", label: "预测步数", type: "input", default: "10" },
    ],
    ab_test: [
      { key: "group_col", label: "分组列", type: "input", default: "" },
      { key: "metric_col", label: "指标列", type: "input", default: "" },
      { key: "test", label: "检验方法", type: "select", options: ["ttest", "mannwhitney", "proportion"], default: "ttest" },
    ],
    sample_size_calc: [
      { key: "effect_size", label: "效应量", type: "input", default: "0.5" },
      { key: "alpha", label: "显著性水平", type: "input", default: "0.05" },
      { key: "power", label: "统计功效", type: "input", default: "0.8" },
    ],
    table_join: [
      { key: "left_table", label: "左表", type: "input", default: "input.csv" },
      { key: "right_table", label: "右表", type: "input", default: "input_2.csv" },
      { key: "left_on", label: "左表关联键", type: "input", default: "" },
      { key: "right_on", label: "右表关联键", type: "input", default: "" },
      { key: "how", label: "关联方式", type: "select", options: ["inner", "left", "right", "outer"], default: "inner" },
    ],
    anomaly_detect: [
      { key: "col", label: "检测列", type: "input", default: "" },
      { key: "threshold", label: "阈值(Z-score)", type: "input", default: "3" },
    ],
    dist_fit: [
      { key: "col", label: "拟合列", type: "input", default: "" },
      { key: "positive_only", label: "仅正值", type: "checkbox", default: true },
    ],
    cluster_profile: [
      { key: "k", label: "聚类数", type: "input", default: "3" },
    ],
    pca_decompose: [
      { key: "n_components", label: "主成分数", type: "input", default: "2" },
    ],
    regression_fit: [
      { key: "feature", label: "特征列", type: "input", default: "" },
      { key: "target", label: "目标列", type: "input", default: "" },
      { key: "degree", label: "多项式阶数", type: "input", default: "1" },
    ],
    model_classify: [
      { key: "target", label: "目标列", type: "input", default: "" },
    ],
  };

  // 会修改数据文件的工具
  const DATA_MUTATORS = ["data_clean", "feature_engineer"];

  const state = {
    mode: "flow",        // "flow" | "workbench"
    stage: "idle",       // flow 模式: idle | running | done
    runId: "",
    runs: [],
    tools: [],
    chat: {},
  };

  function toast(msg, isErr = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "show" + (isErr ? " err" : "");
    setTimeout(() => (t.className = ""), 2600);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    if (res.headers.get("content-type")?.includes("application/json")) return res.json();
    return res.text();
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function formatBytes(b) {
    if (!b) return "0 B";
    const k = 1024, s = ["B","KB","MB","GB"];
    const i = Math.min(s.length - 1, Math.floor(Math.log(b) / Math.log(k)));
    return (b / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1) + " " + s[i];
  }

  function openHelpModal() { $("#helpModal").classList.add("show"); }
  function closeHelpModal() { $("#helpModal").classList.remove("show"); }

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  /* ---- 单页状态机 ---- */
  // stage: "idle" | "running" | "done"
  function setStage(stage) {
    state.stage = stage;
    renderStage();
  }

  function renderStage() {
    const box = $("#stage");
    if (!box) return;
    if (state.mode === "workbench") { renderWorkbench(box); return; }
    const stage = state.stage || "idle";
    if (stage === "idle") renderIdle(box);
    else if (stage === "running") renderRunning(box);
    else if (stage === "done") renderDone(box);
  }

  /* ---- 初始化 ---- */
  async function init() {
    bindApp();
    bindLlmConfig();
    bindHealth();
    bindHelpModal();
    await Promise.all([loadTools(), loadRuns()]);
    renderSidebarRuns();
    setStage("idle");
  }

  /* ---- 绑定单页交互 ---- */
  function setMode(mode) {
    state.mode = mode;
    $$(".mode-nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    renderStage();
  }

  function bindApp() {
    $("#sidebarToggle").addEventListener("click", () => {
      $("#sidebar").classList.toggle("open");
    });
    $("#newRunBtn").addEventListener("click", () => {
      state.runId = null;
      _idleFile = null;
      state.stage = "idle";
      setMode("flow");
    });
    $$("#modeNav .mode-nav-btn").forEach((b) =>
      b.addEventListener("click", () => setMode(b.dataset.mode))
    );
  }

  function bindHelpModal() {
    $("#helpCloseBtn").addEventListener("click", closeHelpModal);
    $("#helpModal").addEventListener("click", (e) => { if (e.target.id === "helpModal") closeHelpModal(); });
  }

  /* ---- idle 态：上传 + 目标输入 ---- */
  let _idleFile = null;

  function renderWorkbench(box) {
    if (!state.runId) renderWorkbenchUpload(box);
    else renderWorkbenchReady(box);
  }

  function renderWorkbenchUpload(box) {
    box.innerHTML = `
      <div class="wb-upload">
        <h2>🛠 工作台</h2>
        <p class="muted">上传 CSV 后，可手动选择单个工具分析，或用自然语言提问。不强制跑全流程。</p>
        <div class="dropzone" id="wbDropzone">
          <div class="icon">↑</div>
          <div class="title">点击或拖拽上传 CSV</div>
          <div class="hint">支持 .csv 格式，最大 200MB</div>
          <input type="file" id="wbFile" accept=".csv,text/csv" style="display:none">
        </div>
        <div id="wbFileName" class="file-selected" style="display:none;margin-top:10px">
          <span class="fs-icon">📄</span><span class="fs-name">—</span><span class="fs-size muted small">—</span><span class="fs-badge">已选择</span>
        </div>
        <div style="margin-top:16px"><button class="btn btn-primary btn-lg" id="wbUploadBtn">上传并开始</button></div>
        <p class="muted small" style="margin-top:8px">想跑完整 Agent 自动编排？切到「全流程分析」。</p>
      </div>`;
    const dz = $("#wbDropzone");
    const input = $("#wbFile");
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault(); dz.classList.remove("dragover");
      if (e.dataTransfer.files[0]) setWbFile(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => { if (input.files[0]) setWbFile(input.files[0]); });
    $("#wbUploadBtn").addEventListener("click", startWorkbench);
  }

  function setWbFile(f) {
    _wbFile = f;
    const box = $("#wbFileName");
    box.style.display = "flex";
    box.querySelector(".fs-name").textContent = f.name;
    box.querySelector(".fs-size").textContent = formatBytes(f.size);
    $("#wbDropzone").classList.add("has-file");
  }

  async function startWorkbench() {
    if (!_wbFile) { toast("请先上传 CSV", true); return; }
    const fd = new FormData();
    fd.append("file", _wbFile);
    fd.append("title", `工作台：${_wbFile.name.slice(0, 20)}`);
    try {
      const r = await fetch("/api/run", { method: "POST", body: fd }).then((r) => r.json());
      state.runId = r.run_id;
      state.wbResults = [];
      _wbFile = null;
      await loadRuns();
      renderSidebarRuns();
      renderStage();
      toast("数据已加载，开始手动分析吧");
    } catch (e) { toast(`上传失败：${e.message}`, true); }
  }

  function renderWorkbenchReady(box) {
    box.innerHTML = `
      <div class="wb-toolbar">
        <span class="muted small">当前数据：RID ${esc(state.runId.slice(0, 10))}…</span>
        <button class="btn btn-sm" id="wbReuploadBtn">↻ 重新上传</button>
      </div>
      <div class="wb-grid">
        <aside class="wb-col wb-toolbox">
          <h3>🧰 工具箱</h3>
          <input class="run-search" id="wbToolSearch" placeholder="搜索工具">
          <div class="wb-tool-groups" id="wbToolGroups"></div>
        </aside>
        <section class="wb-col wb-main">
          <div class="wb-tabs">
            <button class="wb-tab active" data-wbtab="data">📊 数据预览</button>
            <button class="wb-tab" data-wbtab="results">📋 工具结果 <span class="wb-tab-count" id="wbResultCount"></span></button>
          </div>
          <div class="wb-body" id="wbBody"><p class="muted">加载中…</p></div>
        </section>
        <aside class="wb-col wb-nl">
          <h3>💬 自然语言</h3>
          <input class="run-search" id="wbNlQuestion" placeholder="例如：按品类汇总销售额 Top5">
          <div class="flex gap-8" style="margin:8px 0">
            <button class="btn btn-sm btn-primary" id="wbNlFilter">查数</button>
            <button class="btn btn-sm" id="wbNlAgg">聚合</button>
            <button class="btn btn-sm" id="wbNlInsight">洞察</button>
          </div>
          <div id="wbNlResult" class="small" style="white-space:pre-wrap;font-family:var(--font-mono);min-height:60px"></div>
        </aside>
      </div>`;
    $("#wbReuploadBtn").addEventListener("click", () => { state.runId = null; renderStage(); });
    $$(".wb-tab").forEach((t) =>
      t.addEventListener("click", () => {
        $$(".wb-tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        renderWbTab(t.dataset.wbtab);
      })
    );
    $("#wbToolSearch")?.addEventListener("input", renderWbToolbox);
    $("#wbNlFilter").addEventListener("click", () => runWbNL("nl_filter"));
    $("#wbNlAgg").addEventListener("click", () => runWbNL("nl_agg"));
    $("#wbNlInsight").addEventListener("click", () => runWbNL("nl_insight"));
    renderWbToolbox();
    renderWbTab("data");
  }

  function renderWbToolbox() {
    const box = $("#wbToolGroups");
    if (!box) return;
    const term = ($("#wbToolSearch")?.value || "").toLowerCase();
    const byGroup = {};
    state.tools.forEach((t) => {
      const g = TOOL_GROUP[t.name] || "stats";
      if (!byGroup[g]) byGroup[g] = [];
      const label = TOOL_LABEL[t.name] || t.name;
      if (term && !(label.toLowerCase().includes(term) || t.name.toLowerCase().includes(term))) return;
      byGroup[g].push(t);
    });
    let html = "";
    Object.keys(byGroup).forEach((g) => {
      html += `<div class="wb-tool-group"><div class="wtg-head">${GROUP_NAME[g] || g} <span class="muted small">(${byGroup[g].length})</span></div>`;
      byGroup[g].forEach((t) => {
        const hasParams = !!TOOL_PARAMS[t.name];
        html += `<div class="wtg-tool" data-tool="${esc(t.name)}">
          <button class="wtg-btn">
            <span class="t-name">${esc(TOOL_LABEL[t.name] || t.name)}</span>
            ${hasParams ? '<span class="t-gear" title="参数">⚙</span>' : ""}
          </button>
          <div class="wtg-params" style="display:none"></div>
        </div>`;
      });
      html += `</div>`;
    });
    box.innerHTML = html || '<p class="muted small">无匹配工具</p>';
    $$(".wtg-tool").forEach((el) => {
      const name = el.dataset.tool;
      el.querySelector(".wtg-btn").addEventListener("click", (ev) => {
        if (ev.target.classList.contains("t-gear")) {
          const p = el.querySelector(".wtg-params");
          const show = p.style.display !== "block";
          p.style.display = show ? "block" : "none";
          if (show && !p.dataset.built) {
            p.innerHTML = buildToolParamForm(name);
            p.dataset.built = "1";
          }
          return;
        }
        runWbTool(name, collectToolParams(el, name));
      });
    });
  }

  function buildToolParamForm(name) {
    const ps = TOOL_PARAMS[name];
    if (!ps) return "";
    return ps.map((p) => {
      if (p.type === "select") {
        return `<label class="wtg-field"><span>${esc(p.label)}</span>
          <select data-pkey="${esc(p.key)}">${p.options.map((o) => `<option value="${esc(o)}"${o === p.default ? " selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
      }
      if (p.type === "checkbox") {
        return `<label class="wtg-field cb"><input type="checkbox" data-pkey="${esc(p.key)}" data-ptype="cb"${p.default ? " checked" : ""}><span>${esc(p.label)}</span></label>`;
      }
      return `<label class="wtg-field"><span>${esc(p.label)}</span>
        <input type="text" data-pkey="${esc(p.key)}" value="${esc(p.default ?? "")}"></label>`;
    }).join("");
  }

  function collectToolParams(el, name) {
    const params = {};
    if (name === "eda_plot") params.kind = "all";
    if (name === "data_clean") params.fill = "median";
    el.querySelectorAll(".wtg-params [data-pkey]").forEach((inp) => {
      const k = inp.dataset.pkey;
      if (inp.dataset.ptype === "cb") params[k] = inp.checked;
      else if (inp.value !== "") params[k] = inp.value;
    });
    return params;
  }

  if (!state.wbResults) state.wbResults = [];

  async function renderWbTab(tab) {
    const box = $("#wbBody");
    const id = state.runId;
    if (!box || !id) return;
    if (tab === "data") {
      box.innerHTML = '<p class="muted">加载数据…</p>';
      try {
        const d = await api(`/api/run/${id}/data?which=input`);
        if (!d.columns) { box.innerHTML = '<div class="empty"><p>暂无数据</p></div>'; return; }
        let html = `<div class="data-table-wrap"><table class="data-table"><thead><tr>`;
        d.columns.forEach((c) => (html += `<th>${esc(c)}</th>`));
        html += `</tr></thead><tbody>`;
        (d.sample || []).forEach((row) => {
          html += "<tr>";
          d.columns.forEach((c) => (html += `<td>${esc(String(row[c] ?? ""))}</td>`));
          html += "</tr>";
        });
        html += `</tbody></table></div>`;
        html += `<p class="small muted" style="margin-top:10px">共 ${d.rows} 行 × ${d.cols} 列，预览前 10 行</p>`;
        box.innerHTML = html;
      } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
    } else if (tab === "results") {
      if (!state.wbResults.length) {
        box.innerHTML = '<div class="empty"><p>尚未执行任何工具</p><p class="muted small">从左侧工具箱选择一个工具开始</p></div>';
        return;
      }
      let html = "";
      state.wbResults.forEach((r, i) => {
        const wrap = document.createElement("div");
        renderToolResult(r.data, r.tool, wrap);
        html += `<div class="wb-result-card"><div class="wbr-head"><span>${esc(TOOL_LABEL[r.tool] || r.tool)}</span><button class="btn btn-sm btn-ghost" data-rm="${i}">✕</button></div>${wrap.innerHTML}</div>`;
      });
      box.innerHTML = html;
      box.querySelectorAll("[data-rm]").forEach((b) =>
        b.addEventListener("click", () => {
          state.wbResults.splice(+b.dataset.rm, 1);
          renderWbTab("results");
          updateWbResultCount();
        })
      );
    }
  }

  function updateWbResultCount() {
    const el = $("#wbResultCount");
    if (el) el.textContent = state.wbResults.length ? `(${state.wbResults.length})` : "";
  }

  async function runWbTool(name, params) {
    const id = state.runId;
    if (!id) { toast("未选择运行", true); return; }
    toast(`执行 ${TOOL_LABEL[name] || name} …`);
    try {
      const r = await api(`/api/run/${id}/tool`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: name, params }),
      });
      if (r && r.success !== false) {
        state.wbResults.unshift({ tool: name, data: r });
        updateWbResultCount();
        if (DATA_MUTATORS.includes(name)) {
          toast("数据已更新，可在「数据预览」查看");
        } else {
          $$(".wb-tab").forEach((x) => x.classList.remove("active"));
          document.querySelector('.wb-tab[data-wbtab="results"]').classList.add("active");
          renderWbTab("results");
        }
      } else {
        toast(`执行失败：${r.error || "未知"}`, true);
      }
    } catch (e) { toast(`执行失败：${e.message}`, true); }
  }

  async function runWbNL(tool) {
    const id = state.runId;
    if (!id) { toast("未选择运行", true); return; }
    const q = ($("#wbNlQuestion")?.value || "").trim();
    if (!q) { toast("请输入问题", true); return; }
    const out = $("#wbNlResult");
    if (!out) return;
    out.textContent = "思考中…";
    try {
      const r = await api(`/api/run/${id}/tool`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, params: { question: q } }),
      });
      out.textContent = typeof r === "string" ? r : JSON.stringify(r, null, 2);
    } catch (e) { out.textContent = `失败：${e.message}`; }
  }

  function renderIdle(box) {
    box.innerHTML = `
      <div class="idle-hero">
        <h1>全流程分析</h1>
        <p class="lead">上传 CSV + 写一句话目标，Agent 自动规划任务、执行清洗/统计/建模、生成可视化报告。</p>
      </div>
      <div class="idle-form">
        <div class="field-group">
          <label>CSV 文件</label>
          <div class="dropzone" id="idleDropzone">
            <div class="icon">↑</div>
            <div class="title">点击或拖拽上传 CSV</div>
            <div class="hint">支持 .csv 格式，最大 200MB</div>
            <input type="file" id="idleFile" accept=".csv,text/csv" style="display:none">
          </div>
          <div id="idleFileName" class="file-selected" style="display:none;margin-top:10px">
            <span class="fs-icon">📄</span>
            <span class="fs-name">—</span>
            <span class="fs-size muted small">—</span>
            <span class="fs-badge">已选择</span>
          </div>
        </div>
        <div class="field-group">
          <label>分析目标 <span class="muted small">（可选，不填将自动综合探索）</span></label>
          <textarea id="idleGoal" placeholder="描述你关心的分析方向，如：销售额趋势、异常检测、影响因素建模…"></textarea>
          <div class="goal-chips" id="goalChips">
            <span class="chip" data-goal="📈 趋势分析：分析销售额随时间的变化趋势，识别增长或下滑拐点">📈 趋势分析</span>
            <span class="chip" data-goal="🔍 异常检测：识别数据中的离群点与异常值，分析其成因">🔍 异常检测</span>
            <span class="chip" data-goal="🤝 多因素分析：找出影响目标变量的关键因素并构建回归模型">🤝 多因素建模</span>
            <span class="chip" data-goal="📊 综合报告：对这份数据进行全面探索性分析并生成可视化报告">📊 综合报告</span>
          </div>
        </div>
        <div class="idle-actions">
          <button class="btn btn-primary btn-lg" id="idleStartBtn">开始分析</button>
          <button class="btn btn-outline" id="idleHelpBtn">使用引导</button>
        </div>
        <p class="idle-note muted small">不知道怎么用？点「使用引导」查看 CSV 格式与典型场景。Agent 会自动：规划任务 DAG → 执行清洗/统计/建模 → 生成报告</p>
      </div>
    `;
    const dz = $("#idleDropzone");
    const input = $("#idleFile");
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault(); dz.classList.remove("dragover");
      if (e.dataTransfer.files[0]) setIdleFile(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => { if (input.files[0]) setIdleFile(input.files[0]); });
    $("#idleStartBtn").addEventListener("click", startIdle);
    $("#idleHelpBtn").addEventListener("click", openHelpModal);
    $$("#goalChips .chip").forEach((c) => c.addEventListener("click", () => {
      $("#idleGoal").value = c.dataset.goal;
      $$("#goalChips .chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
    }));
  }

  function setIdleFile(f) {
    _idleFile = f;
    const box = $("#idleFileName");
    box.style.display = "flex";
    box.querySelector(".fs-name").textContent = f.name;
    box.querySelector(".fs-size").textContent = formatBytes(f.size);
    $("#idleDropzone").classList.add("has-file");
  }

  async function startIdle() {
    if (!_idleFile) { toast("请先上传 CSV 文件", true); return; }
    const goal = ($("#idleGoal")?.value || "").trim();
    const fd = new FormData();
    fd.append("file", _idleFile);
    fd.append("title", `分析：${(goal || "综合探索").slice(0, 20)}`);
    try {
      const r = await fetch("/api/run", { method: "POST", body: fd }).then((r) => r.json());
      state.runId = r.run_id;
      setStage("running");
      const analyzeFd = new FormData();
      analyzeFd.append("goal", goal);
      analyzeFd.append("async_mode", "true");
      await fetch(`/api/run/${r.run_id}/analyze`, { method: "POST", body: analyzeFd });
      pollRunning();
      await loadRuns();
      renderSidebarRuns();
    } catch (e) { toast(`启动失败：${e.message}`, true); }
  }

  /* ---- running 态：DAG + 日志 + 进度条 ---- */
  function renderRunning(box) {
    box.innerHTML = `
      <div class="running-panel">
        <div class="running-cols">
          <div class="running-col">
            <h3>🧠 任务规划 DAG</h3>
            <div class="thinking-panel" id="runThinking" style="display:none"></div>
            <div class="dag-container" id="runDAG">
              <div class="empty"><div class="icon">🧠</div><p>等待 AI 规划...</p></div>
            </div>
          </div>
          <div class="running-col">
            <h3>📋 执行日志</h3>
            <div class="exec-log" id="runLogs">
              <div class="log-entry muted">等待分析开始...</div>
            </div>
          </div>
        </div>
        <div class="progress-bar" style="margin-top:12px"><i id="runProgressBar" style="width:0%"></i></div>
      </div>
    `;
  }

  async function pollRunning() {
    const id = state.runId;
    if (!id) return;
    try {
      const st = await api(`/api/run/${id}/progress`);
      await updateRunningView(id);
      const bar = $("#runProgressBar");
      if (bar) bar.style.width = (st.progress || 0) + "%";
      if (st.status === "running") {
        setTimeout(pollRunning, 2000);
      } else if (st.status === "done") {
        const mode = st.mode === "llm" ? "LLM 自动编排" : "本地规则模式";
        toast(`全流程分析完成（${mode}）`);
        await loadRuns();
        renderSidebarRuns();
        setStage("done");
      } else if (st.status === "failed") {
        toast(`分析失败：${st.error || ""}`, true);
        setStage("done");
      }
    } catch (e) { setTimeout(pollRunning, 3000); }
  }

  async function updateRunningView(id) {
    try {
      const d = await api(`/api/run/${id}/dag`);
      const dagEl = $("#runDAG");
      const logEl = $("#runLogs");
      const thinkEl = $("#runThinking");
      if (dagEl && d.dag && d.dag.nodes) {
        dagEl.innerHTML = renderDAG(d.dag, d.events || []);
      }
      if (logEl && d.events) {
        logEl.innerHTML = renderExecutionLog(d.events);
        logEl.scrollTop = logEl.scrollHeight;
      }
      if (thinkEl && d.analysis) {
        thinkEl.innerHTML = renderThinking(d.analysis);
        thinkEl.style.display = "block";
      }
    } catch (e) { /* 忽略中途更新错误 */ }
  }

  /* ---- done 态：报告 + 答疑 + 3 tab + 下载 popover ---- */
  async function renderDone(box) {
    const id = state.runId;
    if (!id) { setStage("idle"); return; }
    box.innerHTML = `
      <div class="done-header">
        <h2>分析完成</h2>
        <div class="flex gap-8">
          <div class="dl-wrap">
            <button class="btn btn-outline btn-sm" id="doneDownloadBtn">⬇ 下载 ▾</button>
            <div class="download-popover" id="downloadPopover"></div>
          </div>
          <button class="btn btn-outline btn-sm" id="doneNewBtn">+ 新建分析</button>
        </div>
      </div>
      <div class="done-tabs">
        <button class="done-tab active" data-dtab="report">报告 &amp; 答疑</button>
        <button class="done-tab" data-dtab="result">结果</button>
        <button class="done-tab" data-dtab="trace">执行轨迹</button>
      </div>
      <div class="done-body" id="doneBody"><p class="muted">加载中…</p></div>
      <div class="goal-suggest" id="goalSuggest" style="display:none"></div>
    `;
    $("#doneNewBtn").addEventListener("click", () => {
      state.runId = null; _idleFile = null;
      state.stage = "idle";
      setMode("flow");
    });
    $("#doneDownloadBtn").addEventListener("click", () => {
      $("#downloadPopover").classList.toggle("show");
      renderDownloadPopover(id);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".dl-wrap")) $("#downloadPopover")?.classList.remove("show");
    });
    $$(".done-tab").forEach((t) => t.addEventListener("click", () => {
      $$(".done-tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      renderDoneTab(t.dataset.dtab);
    }));
    loadGoalSuggest(id);
    renderDoneTab("report");
  }

  async function renderDownloadPopover(id) {
    const box = $("#downloadPopover");
    if (!box) return;
    let charts = [];
    try { const d = await api(`/api/run/${id}/charts`); charts = d.charts || []; } catch (e) { /* ignore */ }
    const chartLinks = charts.map((c) =>
      `<a class="dl-item" href="/api/run/${id}/chart?name=${c}" download="${c}"><span>📊</span><span>${esc(c)}</span></a>`
    ).join("");
    box.innerHTML = `
      <a class="dl-item" href="/api/report/${id}" download="report.md"><span>📝</span><span>分析报告 (Markdown)</span></a>
      <a class="dl-item" href="/api/run/${id}/data?which=cleaned" download="cleaned.csv"><span>📄</span><span>清洗后数据 (CSV)</span></a>
      ${chartLinks || '<div class="muted small" style="padding:6px 0">无图表</div>'}
      <a class="dl-item" href="/api/run/${id}/data?which=input" download="input.csv"><span>📥</span><span>原始数据 (CSV)</span></a>
    `;
  }

  async function renderDoneTab(tab) {
    const box = $("#doneBody");
    const id = state.runId;
    if (!box || !id) return;
    if (tab === "report") {
      try {
        const md = await fetch(`/api/report/${id}`).then((r) => r.ok ? r.text() : null);
        if (!md) { box.innerHTML = '<div class="empty"><p>暂无报告</p></div>'; return; }
        box.innerHTML = `<div class="report-chat-grid"><div class="report-pane report-body">${esc(md).replace(/\n/g, "<br>")}</div></div>`;
        renderChatPanel(box.querySelector(".report-chat-grid"), id);
      } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
    } else if (tab === "result") {
      box.innerHTML = '<p class="muted">加载中…</p>';
      try {
        const [chartsRes, dataRes] = await Promise.all([
          api(`/api/run/${id}/charts`).catch(() => ({ charts: [] })),
          api(`/api/run/${id}/data?which=cleaned`).catch(() => null),
        ]);
        let html = '<h3>📊 图表</h3>';
        const charts = chartsRes.charts || [];
        if (charts.length) {
          html += charts.map((c) => `<img src="/api/run/${id}/chart?name=${c}" style="max-width:100%;margin-bottom:12px;border-radius:8px">`).join("");
        } else { html += '<p class="muted">暂无图表</p>'; }
        html += '<h3 style="margin-top:20px">📋 数据预览</h3>';
        if (dataRes && dataRes.columns) {
          html += `<div class="data-table-wrap"><table class="data-table"><thead><tr>`;
          dataRes.columns.forEach((c) => (html += `<th>${esc(c)}</th>`));
          html += `</tr></thead><tbody>`;
          (dataRes.sample || []).forEach((row) => {
            html += "<tr>";
            dataRes.columns.forEach((c) => (html += `<td>${esc(String(row[c] ?? ""))}</td>`));
            html += "</tr>";
          });
          html += `</tbody></table></div>`;
          html += `<p class="small muted" style="margin-top:10px">共 ${dataRes.rows} 行 × ${dataRes.cols} 列，预览前 10 行</p>`;
        } else { html += '<p class="muted">暂无数据</p>'; }
        box.innerHTML = html;
      } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
    } else if (tab === "trace") {
      try {
        const d = await api(`/api/run/${id}/dag`);
        box.innerHTML = `
          ${d.analysis ? `<div class="thinking-panel" style="display:block">${renderThinking(d.analysis)}</div>` : ""}
          <div class="dag-container">${d.dag ? renderDAG(d.dag, d.events || []) : '<p class="muted">暂无</p>'}</div>
          <h3 style="margin-top:16px">📋 执行日志</h3>
          <div class="exec-log">${renderExecutionLog(d.events || [])}</div>
        `;
      } catch (e) { box.innerHTML = `<p class="muted">加载失败</p>`; }
    }
  }

  /* ---- 健康检查 + 运行模式 ---- */
  async function bindHealth() {
    try {
      const h = await api("/api/health");
      setHealth(true);
      setHealthMode(h);
    } catch (e) { setHealth(false); }
  }
  function setHealth(ok) {
    $("#healthText").textContent = ok ? "服务正常" : "服务异常";
    $("#healthDot").className = "health-dot" + (ok ? " ok" : "");
  }
  function setHealthMode(h) {
    const text = $("#modeText");
    const badge = $("#modeBadge");
    if (h && h.mode) {
      text.textContent = h.mode_label || (h.mode === "llm" ? "LLM 智能编排" : "本地规则");
      badge.className = "mode-badge mode-" + h.mode;
    } else {
      text.textContent = "—";
      badge.className = "mode-badge";
    }
  }

  /* ---- LLM 配置弹窗 ---- */
  function bindLlmConfig() {
    const modal = $("#llmModal");
    const status = $("#llmStatus");
    const showStatus = (msg, ok) => {
      status.textContent = msg;
      status.className = "small " + (ok ? "muted" : "err");
      status.style.color = ok ? "var(--success)" : "var(--error)";
    };

    $("#llmConfigBtn").addEventListener("click", async () => {
      status.textContent = "";
      try {
        const c = await api("/api/llm/config");
        $("#llmBaseUrl").value = c.base_url && c.base_url !== "默认" ? c.base_url : "";
        $("#llmModel").value = c.model || "";
        $("#llmApiKey").value = "";
        if (c.using_env_defaults) {
          showStatus("当前使用服务端 .env 默认配置" + (c.model ? `（模型：${c.model}）` : ""), true);
        } else {
          showStatus(`已使用自定义配置（模型：${c.model || "—"}）`, true);
        }
      } catch (e) { showStatus("读取配置失败：" + e.message, false); }
      modal.classList.add("show");
    });

    $("#llmCloseBtn").addEventListener("click", () => modal.classList.remove("show"));
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.remove("show"); });

    $("#llmSaveBtn").addEventListener("click", async () => {
      const body = {
        api_key: $("#llmApiKey").value.trim(),
        base_url: $("#llmBaseUrl").value.trim(),
        model_name: $("#llmModel").value.trim(),
      };
      try {
        const r = await api("/api/llm/config", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (r.success) {
          showStatus(`配置已生效${r.model ? `（模型：${r.model}）` : ""}`, true);
          toast("LLM 配置已更新");
          bindHealth();
        } else {
          showStatus(`配置未生效：${r.error || "未知错误"}`, false);
        }
      } catch (e) { showStatus("保存失败：" + e.message, false); }
    });

    $("#llmResetBtn").addEventListener("click", async () => {
      try {
        const r = await api("/api/llm/config", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: "", base_url: "", model_name: "" }),
        });
        $("#llmApiKey").value = $("#llmBaseUrl").value = $("#llmModel").value = "";
        showStatus(`已恢复 .env 默认配置${r.model ? `（模型：${r.model}）` : ""}`, true);
        toast("已恢复 .env 默认配置");
        bindHealth();
      } catch (e) { showStatus("恢复失败：" + e.message, false); }
    });
  }

  /* ---- 运行列表 ---- */
  async function loadRuns() {
    try {
      const r = await api("/api/runs");
      state.runs = r.runs || [];
      renderSidebarRuns();
    } catch (e) { toast("加载运行列表失败", true); }
  }

  function selectRun(id) {
    state.runId = id;
    renderSidebarRuns();
    $("#sidebar").classList.remove("open");
    setStage("done");
  }

  function avatarColor(s) {
    const colors = ["#2563EB", "#7C3AED", "#06B6D4", "#10B981", "#F59E0B", "#EF4444"];
    let h = 0;
    for (const c of s) h = (h * 31 + c.charCodeAt(0)) % colors.length;
    return colors[h];
  }

  function formatTime(ts) {
    if (!ts) return "";
    const d = new Date(ts);
    return isNaN(d) ? ts : `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
  }

  function renderSidebarRuns() {
    const box = $("#sidebarContent");
    if (!box) return;
    box.innerHTML = '<h3>运行列表</h3><input class="run-search" placeholder="搜索运行标题/RID" id="runSearch">';
    const list = document.createElement("div");
    list.className = "run-list";
    if (!state.runs.length) {
      list.innerHTML = '<div class="empty"><p>暂无运行，点击「新建分析」开始</p></div>';
    } else {
      const term = ($("#runSearch")?.value || "").toLowerCase();
      state.runs
        .filter((r) => (r.title || r.run_id).toLowerCase().includes(term) || r.run_id.toLowerCase().includes(term))
        .forEach((r) => {
          const el = document.createElement("div");
          el.className = "run-item" + (r.run_id === state.runId ? " active" : "");
          const title = r.title || r.run_id.slice(0, 12);
          const avatar = title.slice(0, 2).toUpperCase();
          el.innerHTML = `
            <div class="run-head">
              <div class="flex items-center gap-8">
                <div class="run-avatar" style="background:${avatarColor(r.run_id)}">${avatar}</div>
                <div><div class="bold" style="font-size:13px">${esc(title)}</div><div class="run-meta">RID: ${esc(r.run_id.slice(0, 10))}…</div></div>
              </div>
            </div>
            <div class="run-meta">${formatTime(r.created_at)}</div>
            <div class="run-tags">
              ${r.mode ? `<span class="tag tag-${r.mode === 'llm' ? 'llm' : 'local'}">${r.mode === 'llm' ? 'LLM' : '本地'}</span>` : ""}
              ${r.has_report ? '<span class="tag tag-done">有报告</span>' : ""}
            </div>`;
          el.addEventListener("click", () => selectRun(r.run_id));
          list.appendChild(el);
        });
    }
    box.appendChild(list);
    const search = $("#runSearch");
    if (search) search.addEventListener("input", renderSidebarRuns);
  }

  /* ---- DAG SVG 可视化 ---- */
  function renderDAG(dag, events) {
    const nodes = (dag && dag.nodes) || [];
    const edges = (dag && dag.edges) || [];
    if (!nodes.length) return '<div class="empty"><div class="icon">🧠</div><p>暂无规划数据</p></div>';

    // 从 events 推断节点状态
    const nodeStatus = {};
    (events || []).forEach((e) => {
      const d = e.data || {};
      if (e.event === "tool_start" && d.task_id) nodeStatus[d.task_id] = "running";
      if (e.event === "tool_complete" && d.task_id) nodeStatus[d.task_id] = "done";
      if (e.event === "tool_failed" && d.task_id) nodeStatus[d.task_id] = "failed";
    });

    // 简单分层布局：按依赖深度分层
    const levels = {};
    const inDeg = {};
    nodes.forEach((n) => { inDeg[n.task_id] = (n.dependencies || []).length; });
    let assigned = 0;
    let level = 0;
    const remaining = new Set(nodes.map((n) => n.task_id));
    while (remaining.size > 0 && assigned < nodes.length) {
      const layer = [];
      remaining.forEach((id) => {
        const deps = (nodes.find((n) => n.task_id === id).dependencies) || [];
        if (deps.every((d) => levels[d] !== undefined)) {
          layer.push(id);
        }
      });
      if (!layer.length) {
        remaining.forEach((id) => { levels[id] = level; });
        break;
      }
      layer.forEach((id) => { levels[id] = level; remaining.delete(id); });
      assigned += layer.length;
      level++;
    }

    const maxLevel = Math.max(...Object.values(levels), 0);
    const layerH = 100;
    const nodeW = 200;
    const nodeH = 60;
    const gapX = 40;
    const gapY = 50;
    const svgW = Math.max(600, (Math.max(...nodes.map((n, i) => {
      const same = nodes.filter((nn) => levels[nn.task_id] === levels[n.task_id]);
      return same.length;
    })) || 1) * (nodeW + gapX));
    const svgH = (maxLevel + 1) * (nodeH + gapY) + 20;

    // 计算每层节点位置
    const positions = {};
    const layerCounts = {};
    nodes.forEach((n) => {
      const lv = levels[n.task_id] || 0;
      if (!layerCounts[lv]) layerCounts[lv] = 0;
      const idx = layerCounts[lv]++;
      const layerNodes = nodes.filter((nn) => levels[nn.task_id] === lv);
      const totalW = layerNodes.length * (nodeW + gapX) - gapX;
      const startX = (svgW - totalW) / 2;
      positions[n.task_id] = { x: startX + idx * (nodeW + gapX), y: lv * (nodeH + gapY) + 10 };
    });

    let svg = `<svg class="dag-svg" viewBox="0 0 ${svgW} ${svgH}" style="width:100%;max-width:${svgW}px">`;

    // 边
    edges.forEach((e) => {
      const from = positions[e.from];
      const to = positions[e.to];
      if (!from || !to) return;
      const x1 = from.x + nodeW / 2;
      const y1 = from.y + nodeH;
      const x2 = to.x + nodeW / 2;
      const y2 = to.y;
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="dag-edge" marker-end="url(#arrow)"/>`;
    });

    // 箭头标记
    svg += `<defs><marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" class="dag-arrow"/></marker></defs>`;

    // 节点
    nodes.forEach((n) => {
      const pos = positions[n.task_id];
      if (!pos) return;
      const status = nodeStatus[n.task_id] || n.status || "pending";
      const desc = (n.description || "").substring(0, 30);
      const toolName = TOOL_LABEL[n.metadata?.tool] || n.metadata?.tool || "";
      const statusIcon = { done: "✅", running: "🔄", failed: "❌", pending: "⏳" }[status] || "⏳";
      svg += `<g class="dag-node ${status}" transform="translate(${pos.x},${pos.y})">`;
      svg += `<rect width="${nodeW}" height="${nodeH}" rx="8" />`;
      svg += `<text x="10" y="22" class="dag-node-title">${esc(desc)}</text>`;
      if (toolName) svg += `<text x="10" y="40" class="dag-node-tool">🔧 ${esc(toolName)}</text>`;
      svg += `<text x="${nodeW - 10}" y="22" text-anchor="end" class="dag-node-status">${statusIcon}</text>`;
      svg += `</g>`;
    });

    svg += "</svg>";
    return svg;
  }

  /* ---- 思考过程面板 ---- */
  function renderThinking(analysis) {
    if (!analysis) return "";
    return `<div class="thinking-panel show"><div class="tp-icon">🧠</div><div class="tp-body"><div class="tp-label">AI 分析思路</div><p>${esc(analysis)}</p></div></div>`;
  }

  /* ---- 执行日志流 ---- */
  function renderExecutionLog(events) {
    if (!events || !events.length) return '<div class="log-entry muted">暂无执行日志</div>';
    const eventMap = {
      "agent_start": { icon: "🚀", text: (d) => "Agent 启动", cls: "thinking" },
      "planning_start": { icon: "🧠", text: (d) => "AI 正在规划分析路径...", cls: "thinking" },
      "planning_complete": { icon: "✅", text: (d) => `规划完成：${d.node_count || 0} 个子任务`, cls: "success" },
      "plan_verified": { icon: "✅", text: (d) => `规划验证通过（score: ${d.score || "?"}/100）`, cls: "success" },
      "plan_improvement_needed": { icon: "⚠️", text: (d) => `规划需要改进（${d.suggestions?.length || 0} 条建议）`, cls: "warning" },
      "tool_start": { icon: "🔧", text: (d) => `正在执行：${TOOL_LABEL[d.tool] || d.tool || d.task_desc || "未知工具"}...`, cls: "tool" },
      "tool_complete": { icon: "✅", text: (d) => `${TOOL_LABEL[d.tool] || d.tool || "工具"}完成${d.duration ? `（${d.duration}s）` : ""}`, cls: "success" },
      "tool_failed": { icon: "❌", text: (d) => `${TOOL_LABEL[d.tool] || d.tool || "工具"}失败：${esc(d.error || "")}`, cls: "error" },
      "dag_stuck": { icon: "⚠️", text: (d) => `DAG 卡住，尝试重新规划...`, cls: "warning" },
      "replan_partial_start": { icon: "🔄", text: (d) => `局部重新规划...`, cls: "thinking" },
      "replan_partial_complete": { icon: "✅", text: (d) => `重新规划完成`, cls: "success" },
      "schedule_cycle_start": { icon: "📋", text: (d) => `调度循环开始`, cls: "thinking" },
      "tasks_failed": { icon: "❌", text: (d) => `${(d.tasks || []).length} 个任务失败`, cls: "error" },
      "agent_complete": { icon: "📊", text: (d) => `分析完成${d.duration ? `（耗时 ${d.duration.toFixed(1)}s）` : ""}`, cls: "report" },
      "max_replan_exceeded": { icon: "❌", text: (d) => `重新规划次数超限`, cls: "error" },
      "planning_skipped": { icon: "⏭️", text: (d) => `任务过于简单，跳过规划`, cls: "warning" },
    };
    return events.map((e) => {
      const cfg = eventMap[e.event] || { icon: "•", text: (d) => e.event, cls: "" };
      const text = cfg.text(e.data || {});
      const t = new Date((e.timestamp || 0) * 1000).toLocaleTimeString("zh-CN", { hour12: false });
      const elapsed = e.elapsed != null ? `+${e.elapsed.toFixed(1)}s` : "";
      return `<div class="log-entry ${cfg.cls}"><span class="log-time">${t} ${elapsed}</span> <span class="log-icon">${cfg.icon}</span> <span class="log-text">${text}</span></div>`;
    }).join("");
  }

  // 通用渲染：把对象数组渲染成表格
  function objTable(list) {
    if (!Array.isArray(list) || !list.length) return "";
    const cols = Object.keys(list[0] || {});
    if (!cols.length) return "";
    let h = `<div class="table-wrap"><table class="data"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`;
    list.forEach((row) => {
      h += "<tr>" + cols.map((c) => {
        const cell = row[c];
        return `<td>${esc(typeof cell === "object" ? JSON.stringify(cell) : String(cell ?? ""))}</td>`;
      }).join("") + "</tr>";
    });
    return h + "</tbody></table></div>";
  }

  // 通用渲染：键值对列表
  function renderKV(obj) {
    const kv = Object.entries(obj);
    if (!kv.length) return "";
    return '<div class="kv-list">' + kv.map(([k, v]) => {
      let inner;
      if (Array.isArray(v)) inner = `<code>${esc(v.map((x) => typeof x === "object" ? JSON.stringify(x) : String(x)).join(", "))}</code>`;
      else if (v && typeof v === "object") inner = `<pre>${esc(JSON.stringify(v, null, 2))}</pre>`;
      else inner = `<code>${esc(String(v))}</code>`;
      return `<div class="kv-item"><span class="k">${esc(k)}</span><span class="v">${inner}</span></div>`;
    }).join("") + '</div>';
  }

  // 工具结果解释：异步调 LLM 生成，先渲染占位，返回后填充
  function toolExplainPlaceholder() {
    return `<div class="tool-explain" id="toolExplainBox"><div class="te-icon">💡</div><div class="te-body"><p class="te-loading">正在生成解读…</p></div></div>`;
  }

  async function loadToolExplain(tool, data, container) {
    const box = container.querySelector("#toolExplainBox");
    if (!box || !data || data.success === false) return;
    try {
      const r = await api(`/api/run/${state.runId}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, result: data }),
      });
      const explain = r.explain || "暂无解读。";
      const tag = r.used_llm ? '<div class="chat-tag">· LLM 生成</div>' : "";
      box.querySelector(".te-body").innerHTML = `<p>${esc(explain).replace(/\n/g, "<br>")}</p>${tag}`;
    } catch (e) {
      box.querySelector(".te-body").innerHTML = `<p class="muted">解读加载失败：${esc(e.message)}</p>`;
    }
  }

  // 渲染工具执行结果到指定容器
  function renderToolResult(data, tool, container) {
    if (!data || data.success === false) {
      container.innerHTML = `<p class="muted">工具执行失败${data?.error ? `：${esc(data.error)}` : ""}</p>`;
      return;
    }
    const label = TOOL_LABEL[tool] || tool;
    const metaKeys = ["success", "tool", "meta_file", "chart"];
    let html = `<div class="panel-card"><h3>工具结果 · ${esc(label)}</h3>`;
    html += toolExplainPlaceholder();
    if (data.chart) {
      html += `<div class="chart-card chart-single" id="plotlyChart"></div>`;
    }
    Object.entries(data).forEach(([k, v]) => {
      if (metaKeys.includes(k)) return;
      if (Array.isArray(v) && v.length && typeof v[0] === "object" && v[0] !== null) {
        html += `<h4 class="kv-title">${esc(k)}</h4>` + objTable(v);
      }
    });
    const kv = Object.entries(data).filter(([k, v]) => !metaKeys.includes(k) && !(Array.isArray(v) && v.length && typeof v[0] === "object" && v[0] !== null));
    if (kv.length) {
      html += '<div class="kv-list">' + kv.map(([k, v]) => {
        let inner;
        if (Array.isArray(v)) inner = `<code>${esc(v.map((x) => typeof x === "object" ? JSON.stringify(x) : String(x)).join(", "))}</code>`;
        else if (v && typeof v === "object") inner = `<pre>${esc(JSON.stringify(v, null, 2))}</pre>`;
        else inner = `<code>${esc(String(v))}</code>`;
        return `<div class="kv-item"><span class="k">${esc(k)}</span><span class="v">${inner}</span></div>`;
      }).join("") + '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
    if (data.chart) {
      const chartDiv = container.querySelector("#plotlyChart");
      if (chartDiv) loadInteractiveChart(data.chart, tool, data, chartDiv);
    }
    loadToolExplain(tool, data, container);
  }

  // 交互式图表：优先 Plotly，降级 PNG
  async function loadInteractiveChart(chartName, tool, data, container) {
    if (!container) return;
    if (typeof Plotly === "undefined") {
      container.innerHTML = `<img src="/api/run/${state.runId}/chart?name=${encodeURIComponent(chartName)}" alt="${esc(chartName)}" style="max-width:100%">`;
      return;
    }
    try {
      const r = await api(`/api/run/${state.runId}/chart_data?name=${encodeURIComponent(chartName)}`);
      renderPlotlyChart(r, tool, data, container);
    } catch (e) {
      container.innerHTML = `<img src="/api/run/${state.runId}/chart?name=${encodeURIComponent(chartName)}" alt="${esc(chartName)}" style="max-width:100%">`;
    }
  }

  function renderPlotlyChart(r, tool, data, container) {
    const type = r.chart_type;
    if (type === "dist_fit") {
      api(`/api/run/${state.runId}/data?which=cleaned-or-input`).then(d => {
        const col = data.col;
        const values = (d.rows || []).map(row => parseFloat(row[col])).filter(v => !isNaN(v));
        Plotly.newPlot(container, [
          { x: values, type: "histogram", name: "实际数据", opacity: 0.6, nbinsx: 30, marker: { color: "#4c8bf5" } },
        ], { title: `${col} 分布拟合`, xaxis: { title: col }, yaxis: { title: "频数" },
          margin: { l: 50, r: 20, t: 40, b: 40 } }, { responsive: true });
      }).catch(() => { container.innerHTML = `<img src="/api/run/${state.runId}/chart?name=${encodeURIComponent(data.chart)}" style="max-width:100%">`; });
    } else if (type === "anomaly") {
      const outliers = (data.outliers || []).map(o => o.value);
      Plotly.newPlot(container, [{ y: outliers, mode: "markers", type: "scatter", name: "离群点",
        marker: { color: "red", size: 8 } }], { title: "离群点检测" }, { responsive: true });
    } else if (type === "cluster" && r.meta) {
      const profiles = r.meta.profiles || {};
      const groups = Object.keys(profiles);
      const firstKey = groups[0] || "0";
      const cols = Object.keys(profiles[firstKey] || {});
      const traces = cols.map((c, i) => ({
        x: groups, y: groups.map(g => (profiles[g] || {})[c] || 0),
        type: "bar", name: c,
      }));
      Plotly.newPlot(container, traces, { title: "聚类画像", barmode: "group" }, { responsive: true });
    } else if (type === "forecast" && r.meta) {
      const fc = r.meta.forecast || [];
      Plotly.newPlot(container, [
        { y: fc, type: "scatter", mode: "lines", name: "预测", line: { color: "#e5532f", width: 2 } },
      ], { title: "时序预测" }, { responsive: true });
    } else {
      container.innerHTML = `<img src="/api/run/${state.runId}/chart?name=${encodeURIComponent(data.chart)}" style="max-width:100%">`;
    }
  }

  // -- 数据答疑对话面板 --
  function renderChatMessages(runId, list, msgEl) {
    if (!msgEl || !list) return;
    msgEl.innerHTML = list.length
      ? list.map((m) => {
          if (m.role === "notice") return `<div class="chat-notice">⚠ ${esc(m.text).replace(/\n/g, "<br>")}</div>`;
          return `
          <div class="chat-msg ${m.role === "user" ? "chat-user" : "chat-ai"}">
            <div class="chat-role">${m.role === "user" ? "你" : "AI"}</div>
            <div class="chat-text">${esc(m.text).replace(/\n/g, "<br>")}</div>
            ${m.used_llm ? '<div class="chat-tag">· LLM 生成</div>' : ""}
          </div>`;
        }).join("")
      : '<div class="chat-empty">基于本次分析结果向我提问，例如「哪些特征最影响销量？」</div>';
    const listEl = msgEl.parentElement.querySelector(".chat-list");
    if (listEl) listEl.scrollTo(0, listEl.scrollHeight);
  }

  function renderChatPanel(box, runId) {
    const panel = document.createElement("div");
    panel.className = "chat-panel";
    panel.innerHTML = `
      <div class="chat-head">💬 数据答疑 <span class="muted small">AI 基于本次分析产物回答</span></div>
      <div class="chat-list"><div class="chat-msgs"></div></div>
      <div class="chat-box">
        <input type="text" class="chat-input" placeholder="输入问题，如：各区域销量如何？数据有无离群？">
        <button type="button" class="btn btn-primary chat-send">发送</button>
      </div>`;
    box.appendChild(panel);
    const msgEl = panel.querySelector(".chat-msgs");
    const input = panel.querySelector(".chat-input");
    const list = state.chat[runId] || (state.chat[runId] = []);
    renderChatMessages(runId, list, msgEl);
    const send = async () => {
      const q = input.value.trim();
      if (!q) return;
      list.push({ role: "user", text: q });
      input.value = "";
      renderChatMessages(runId, list, msgEl);
      try {
        const res = await api(`/api/run/${runId}/chat`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q }),
        });
        list.push({ role: "assistant", text: res.answer, used_llm: res.used_llm });
        if (!res.used_llm && res.reason) list.push({ role: "notice", text: res.reason });
      } catch (e) {
        list.push({ role: "assistant", text: "出错了：" + e.message });
      }
      renderChatMessages(runId, list, msgEl);
    };
    panel.querySelector(".chat-send").addEventListener("click", send);
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") send(); });
  }

  /* ---- 目标建议：基于数据的分析方向 chips ---- */
  async function loadGoalSuggest(rid) {
    const box = $("#goalSuggest");
    if (!box || !rid) return;
    try {
      const r = await api(`/api/run/${rid}/suggest-goals`);
      const goals = r.goals || r.suggestions || [];
      if (!goals.length) { box.style.display = "none"; return; }
      box.innerHTML = `
        <div class="gs-label">💡 基于你的数据，还可以这样分析：</div>
        <div class="gs-chips">
          ${goals.map((g) => `<span class="gs-chip" data-goal="${esc(g)}">${esc(g)}</span>`).join("")}
        </div>
      `;
      box.style.display = "block";
      $$(".gs-chip").forEach((c) => c.addEventListener("click", () => {
        state.runId = null;
        _idleFile = null;
        setStage("idle");
        setTimeout(() => {
          const goalEl = $("#idleGoal");
          if (goalEl) goalEl.value = c.dataset.goal;
        }, 50);
      }));
    } catch (e) { box.style.display = "none"; }
  }

  /* ---- 工具加载 ---- */
  async function loadTools() {
    try {
      const r = await api("/api/tools");
      state.tools = r.tools || [];
    } catch (e) { toast("加载工具失败", true); }
  }

  /* ---- 启动 ---- */
  init();
})();
