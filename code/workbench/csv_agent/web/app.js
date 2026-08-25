/* AI 数据分析 Agent 工作台前端逻辑（多视图 SPA） */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const state = {
    runId: "",
    runs: [],
    tools: [],
    wbTab: "data",
    // 最近一次工具执行结果（工作台「工具结果」页展示）
    toolResult: null,
    sidebarSection: "runs",
    flowRunId: "",
    flowTab: "report",
    // run_id -> [{role:'user'|'assistant', text, used_llm}] 数据答疑对话缓存
    chat: {},
  };

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

  // 工具参数配置表：声明每个工具支持的参数及 UI 类型
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

  function showView(name) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
    if (name === "workbench") renderWorkbench();
  }

  /* ---- 初始化 ---- */
  async function init() {
    bindNav();
    bindHome();
    bindWorkbench();
    bindFlow();
    bindLlmConfig();
    bindHealth();
    await Promise.all([loadTools(), loadRuns(), loadHistory()]);
    showView("home");
  }

  function bindNav() {
    $("#navHome").addEventListener("click", () => showView("home"));
    $("#navWorkbench").addEventListener("click", () => showView("workbench"));
    $("#navFlow").addEventListener("click", () => showView("flow"));
  }

  /* ---- 健康检查 + 运行模式 ---- */
  async function bindHealth() {
    try {
      const h = await api("/api/health");
      setHealth(true);
      setMode(h);
    } catch (e) { setHealth(false); }
  }
  function setHealth(ok) {
    $("#healthText").textContent = ok ? "服务正常" : "服务异常";
    $("#healthDot").className = "health-dot" + (ok ? " ok" : "");
  }
  function setMode(h) {
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

  /* ---- 首页 ---- */
  function bindHome() {
    $("#homeUploadBtn").addEventListener("click", () => showView("flow"));
    $("#homeWorkbenchBtn").addEventListener("click", () => showView("workbench"));
  }

  /* ---- 运行列表 ---- */
  async function loadRuns() {
    try {
      const r = await api("/api/runs");
      state.runs = r.runs || [];
      renderSidebarRuns();
      if (!state.runId && state.runs.length) selectRun(state.runs[0].run_id);
    } catch (e) { toast("加载运行列表失败", true); }
  }

  function selectRun(id) {
    state.runId = id;
    renderSidebarRuns();
    renderWorkbench();
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

  /* ---- 工作台 ---- */
  function bindWorkbench() {
    $("#newRunBtn").addEventListener("click", () => showView("flow"));
    $("#wbRefreshBtn").addEventListener("click", async () => {
      await Promise.all([loadRuns(), loadTools(), loadHistory()]);
      renderWorkbench();
      toast("已刷新");
    });

    $$(".nav-item").forEach((n) => n.addEventListener("click", () => {
      state.sidebarSection = n.dataset.section;
      $$(".nav-item").forEach((x) => x.classList.toggle("active", x === n));
      renderSidebar();
    }));

    $$("#wbTabs .toolbar-tab").forEach((t) => t.addEventListener("click", () => {
      state.wbTab = t.dataset.tab;
      $$("#wbTabs .toolbar-tab").forEach((x) => x.classList.toggle("active", x === t));
      renderWorkbenchContent();
    }));
  }

  function renderSidebar() {
    if (state.sidebarSection === "runs") renderSidebarRuns();
    else if (state.sidebarSection === "tools") renderSidebarTools();
    else if (state.sidebarSection === "nl") renderSidebarNL();
    else if (state.sidebarSection === "history") renderSidebarHistory();
  }

  function renderSidebarRuns() {
    const box = $("#sidebarContent");
    box.innerHTML = '<h3>运行列表</h3><input class="run-search" placeholder="搜索运行标题/RID" id="runSearch">';
    const list = document.createElement("div");
    list.className = "run-list";
    if (!state.runs.length) {
      list.innerHTML = '<div class="empty"><p>暂无运行，点击「新建运行」开始</p></div>';
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

  function renderSidebarTools() {
    const box = $("#sidebarContent");
    box.innerHTML = '<h3>工具箱</h3><div class="tool-grid" id="sidebarTools"></div>';
    const grid = $("#sidebarTools");
    state.tools.forEach((t) => {
      const btn = document.createElement("button");
      btn.className = "tool-btn";
      btn.innerHTML = `<span class="t-name">${esc(TOOL_LABEL[t.name] || t.name)}</span><span class="t-desc">${esc(t.description || "")}</span>`;
      btn.addEventListener("click", () => runTool(t.name, btn));
      grid.appendChild(btn);
    });
  }

  function renderSidebarNL() {
    const box = $("#sidebarContent");
    box.innerHTML = `
      <h3>自然语言查数</h3>
      <p class="small muted" style="margin-bottom:12px">选中运行后，输入问题即可调用智能查数/聚合/洞察。</p>
      <div class="field-group" style="margin-bottom:10px">
        <input class="run-search" id="nlQuestion" placeholder="例如：按品类汇总销售额 Top5">
      </div>
      <div class="flex gap-8" style="margin-bottom:12px">
        <button class="btn btn-sm btn-primary" id="nlFilterBtn">智能查数</button>
        <button class="btn btn-sm" id="nlAggBtn">分组聚合</button>
        <button class="btn btn-sm" id="nlInsightBtn">智能洞察</button>
      </div>
      <div id="nlResult" class="small" style="white-space:pre-wrap;font-family:var(--font-mono)"></div>`;
    $("#nlFilterBtn").addEventListener("click", () => runNL("nl_filter"));
    $("#nlAggBtn").addEventListener("click", () => runNL("nl_agg"));
    $("#nlInsightBtn").addEventListener("click", () => runNL("nl_insight"));
  }

  async function runNL(tool) {
    if (!state.runId) { toast("请先选择运行", true); return; }
    const q = $("#nlQuestion").value.trim();
    if (!q) { toast("请输入问题", true); return; }
    const out = $("#nlResult");
    out.textContent = "思考中…";
    try {
      const r = await api(`/api/run/${state.runId}/tool`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, params: { question: q } }),
      });
      out.textContent = JSON.stringify(r, null, 2);
      toast(r.success ? "查询完成" : "查询失败", !r.success);
    } catch (e) { out.textContent = e.message; toast(e.message, true); }
  }

  async function renderSidebarHistory() {
    const box = $("#sidebarContent");
    box.innerHTML = '<h3>历史记录</h3><div id="historyList"></div>';
    try {
      const r = await api("/api/history");
      const list = $("#historyList");
      if (!r.history.length) { list.innerHTML = '<div class="empty"><p>暂无历史记录</p></div>'; return; }
      list.innerHTML = r.history.map((h) => `
        <div class="run-item" style="margin-bottom:8px">
          <div class="bold" style="font-size:13px">${esc(h.goal)}</div>
          <div class="run-meta">${esc(h.ts)} · 列: ${esc(h.columns.join(", "))} · 模型: ${esc(h.model || "—")}</div>
        </div>`).join("");
    } catch (e) { box.innerHTML += `<p class="small muted">加载失败：${esc(e.message)}</p>`; }
  }

  function renderWorkbench() {
    renderSidebar();
    const run = state.runs.find((r) => r.run_id === state.runId);
    if (run) {
      $("#mainTitle").textContent = run.title || run.run_id;
      $("#mainBreadcrumb").innerHTML = `运行 <b>${esc(run.run_id)}</b> ${run.has_report ? "· 有报告" : ""} ${run.has_cleaned ? "· 已清洗" : ""}`;
    } else {
      $("#mainTitle").textContent = "运行详情";
      $("#mainBreadcrumb").textContent = "选择左侧运行以查看数据与产物";
    }
    renderWorkbenchContent();
  }

  function renderWorkbenchContent() {
    const box = $("#wbContent");
    if (!state.runId) {
      box.innerHTML = '<div class="empty"><div class="icon">▦</div><p>选择左侧运行，开始查看数据、图表与报告</p></div>';
      return;
    }
    if (state.wbTab === "data") loadData();
    else if (state.wbTab === "tools") renderToolsTab();
    else if (state.wbTab === "tool-result") renderToolResult();
    else if (state.wbTab === "explore") renderExplore();
    else if (state.wbTab === "charts") loadCharts();
    else if (state.wbTab === "report") loadReport();
    else if (state.wbTab === "trace") loadTrace();
    else if (state.wbTab === "download") renderDownloads();
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

  // 展示最近一次工具执行结果（分布拟合/相关/异常等返回真实数值结果，而非数据预览）
  // 工具结果解释：异步调 LLM 生成，先渲染占位，返回后填充
  function toolExplainPlaceholder() {
    return `<div class="tool-explain" id="toolExplainBox"><div class="te-icon">💡</div><div class="te-body"><p class="te-loading">正在生成解读…</p></div></div>`;
  }

  async function loadToolExplain(tool, data) {
    const box = $("#toolExplainBox");
    if (!box || !data || !data.success) return;
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

  function renderToolResult() {
    const box = $("#wbContent");
    const tr = state.toolResult;
    if (!tr || !tr.data) {
      box.innerHTML = '<div class="empty"><div class="icon">▧</div><p>暂无工具执行结果，请先在「分步工具」中执行一个分析</p></div>';
      return;
    }
    const { tool, data } = tr;
    const label = TOOL_LABEL[tool] || tool;
    const metaKeys = ["success", "tool", "meta_file", "chart"];
    let html = `<div class="panel-card"><h3>工具结果 · ${esc(label)}</h3>`;
    html += toolExplainPlaceholder();
    if (data.chart) {
      // 优先尝试 Plotly 交互式渲染，不可用时降级为 PNG
      html += `<div id="plotlyChart" class="chart-card chart-single"></div>`;
      setTimeout(() => loadInteractiveChart(data.chart, tool, data), 50);
    }
    // 数组字段（如 results）渲染成表格
    Object.entries(data).forEach(([k, v]) => {
      if (metaKeys.includes(k)) return;
      if (Array.isArray(v) && v.length && typeof v[0] === "object" && v[0] !== null) {
        html += `<h4 class="kv-title">${esc(k)}</h4>` + objTable(v);
      }
    });
    // 其余标量字段渲染成键值对
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
    box.innerHTML = html;
    // 异步加载 LLM 解释
    loadToolExplain(tool, data);
  }

  // 交互式图表：优先 Plotly，降级 PNG
  async function loadInteractiveChart(chartName, tool, data) {
    const container = $("#plotlyChart");
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

  // 数据探索：即时筛选/分组/统计，不修改原数据
  const EXPLORE_ACTIONS = [
    { value: "describe", label: "描述统计" },
    { value: "filter", label: "条件筛选" },
    { value: "group", label: "分组聚合" },
    { value: "correlate", label: "相关性矩阵" },
  ];
  const exploreState = { action: "describe", cols: [] };

  async function renderExplore() {
    const box = $("#wbContent");
    if (!state.runId) return;
    // 拉取列名以填充下拉
    try {
      const d = await api(`/api/run/${state.runId}/data?which=auto`);
      exploreState.cols = d.columns || [];
    } catch (e) { exploreState.cols = []; }
    box.innerHTML = `<div class="panel-card"><h3>数据探索 <span class="small muted">基于 cleaned.csv（无则 input.csv），不修改原数据</span></h3>
      <div class="field-group" style="margin-bottom:12px">
        <label>探索方式</label>
        <select id="exploreAction" class="run-search">
          ${EXPLORE_ACTIONS.map((a) => `<option value="${a.value}"${a.value === exploreState.action ? " selected" : ""}>${esc(a.label)}</option>`).join("")}
        </select>
      </div>
      <div id="exploreParams"></div>
      <div class="flex gap-8" style="margin-top:10px">
        <button class="btn btn-sm btn-primary" id="exploreRunBtn">执行</button>
      </div>
      <div id="exploreResult" style="margin-top:14px"></div>
    </div>`;
    renderExploreParams();
    $("#exploreAction").addEventListener("change", (e) => {
      exploreState.action = e.target.value;
      renderExploreParams();
    });
    $("#exploreRunBtn").addEventListener("click", runExplore);
  }

  function renderExploreParams() {
    const box = $("#exploreParams");
    const action = exploreState.action;
    const colOpts = exploreState.cols.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    let html = "";
    if (action === "filter") {
      html = `<div class="flex gap-8" style="flex-wrap:wrap;align-items:end">
        <label class="field" style="margin:0"><span>列</span><select id="exCol" class="run-search">${colOpts}</select></label>
        <label class="field" style="margin:0"><span>运算符</span>
          <select id="exOp" class="run-search">${[">", "<", "==", ">=", "<="].map((o) => `<option value="${o}">${o}</option>`).join("")}</select></label>
        <label class="field" style="margin:0"><span>值</span><input id="exVal" class="run-search" type="number" step="any" value="0"></label>
      </div>`;
    } else if (action === "group") {
      html = `<div class="flex gap-8" style="flex-wrap:wrap;align-items:end">
        <label class="field" style="margin:0"><span>分组列</span><select id="exGroupCol" class="run-search">${colOpts}</select></label>
        <label class="field" style="margin:0"><span>聚合列</span><select id="exAggCol" class="run-search">${colOpts}</select></label>
        <label class="field" style="margin:0"><span>聚合函数</span>
          <select id="exAggFunc" class="run-search">${["mean", "sum", "count", "min", "max"].map((f) => `<option value="${f}">${f}</option>`).join("")}</select></label>
      </div>`;
    } else if (action === "correlate") {
      html = `<div class="field-group">
        <label>数值列 <span class="muted small">（留空则自动选所有数值列；多列用逗号分隔）</span></label>
        <input id="exCols" class="run-search" placeholder="如 sales,quantity">
      </div>`;
    } else {
      html = `<p class="small muted">描述统计无需额外参数，直接点「执行」。</p>`;
    }
    box.innerHTML = html;
  }

  async function runExplore() {
    if (!state.runId) { toast("请先选择运行", true); return; }
    const action = exploreState.action;
    const params = {};
    if (action === "filter") {
      params.col = $("#exCol")?.value || "";
      params.op = $("#exOp")?.value || ">";
      params.value = parseFloat($("#exVal")?.value || "0");
    } else if (action === "group") {
      params.group_col = $("#exGroupCol")?.value || "";
      params.agg_col = $("#exAggCol")?.value || "";
      params.agg_func = $("#exAggFunc")?.value || "mean";
    } else if (action === "correlate") {
      const raw = ($("#exCols")?.value || "").trim();
      if (raw) params.cols = raw.split(",").map((s) => s.trim()).filter(Boolean);
    }
    const out = $("#exploreResult");
    out.innerHTML = '<p class="muted">执行中…</p>';
    try {
      const r = await api(`/api/run/${state.runId}/explore`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, params }),
      });
      out.innerHTML = renderExploreResult(action, r.result);
      toast("探索完成");
    } catch (e) {
      out.innerHTML = `<p class="muted">执行失败：${esc(e.message)}</p>`;
    }
  }

  function renderExploreResult(action, result) {
    if (!result) return '<p class="muted">无结果</p>';
    if (result.error) return `<p class="muted">${esc(result.error)}</p>`;
    let html = "";
    if (action === "filter") {
      html += `<p class="small muted">筛选后共 ${result.rows ?? 0} 行</p>`;
      html += objTable(result.sample || []);
    } else if (action === "group") {
      html += objTable(result.groups || []);
    } else if (action === "describe") {
      // describe 返回 {col: {stat: val}}，转成行表格
      const stats = Object.keys(result);
      const cols = stats.length ? Object.keys(result[stats[0]] || {}) : [];
      const rows = cols.map((c) => {
        const row = { 统计: c };
        stats.forEach((s) => { row[s] = result[s][c]; });
        return row;
      });
      html += objTable(rows);
    } else if (action === "correlate") {
      const matrix = result.matrix || {};
      const cols = Object.keys(matrix);
      const rows = cols.map((c) => {
        const row = { "": c };
        cols.forEach((c2) => { row[c2] = matrix[c][c2]; });
        return row;
      });
      html += objTable(rows);
    }
    return html || '<p class="muted">无结果</p>';
  }

  async function loadRunInfoShort() {
    if (!state.runId) return;
    try {
      const r = await api(`/api/run/${state.runId}/info`);
      $("#mainTitle").textContent = r.title || r.run_id;
      $("#mainBreadcrumb").innerHTML = `运行 <b>${esc(r.run_id)}</b> · ${r.rows || 0} 行 × ${r.cols || 0} 列 · ${r.has_report ? "有报告" : "无报告"}`;
    } catch (e) { /* ignore */ }
  }

  async function loadData(which = "auto") {
    const box = $("#wbContent");
    if (!state.runId) return;
    box.innerHTML = '<p class="muted">加载数据中…</p>';
    try {
      const r = await api(`/api/run/${state.runId}/data?which=${which}`);
      let html = `<div class="panel-card"><h3>数据预览 <span class="small muted">(${which === "auto" ? "自动" : which})</span></h3>`;
      html += `<div class="flex gap-8" style="margin-bottom:12px">
        <button class="btn btn-sm ${which === "input" ? "btn-primary" : ""}" onclick="window.__setData('input')">原始 input</button>
        <button class="btn btn-sm ${which === "cleaned" ? "btn-primary" : ""}" onclick="window.__setData('cleaned')">清洗后</button>
      </div>`;
      html += `<div class="table-wrap"><table class="data"><thead><tr>`;
      r.columns.forEach((c) => (html += `<th>${esc(c)}</th>`));
      html += `</tr></thead><tbody>`;
      r.sample.forEach((row) => {
        html += "<tr>";
        r.columns.forEach((c) => (html += `<td>${esc(String(row[c] ?? ""))}</td>`));
        html += "</tr>";
      });
      html += `</tbody></table></div><p class="small muted" style="margin-top:10px">共 ${r.rows} 行 × ${r.cols} 列，预览前 10 行</p></div>`;
      box.innerHTML = html;
      loadRunInfoShort();
    } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }
  window.__setData = (which) => loadData(which);

  function renderToolsTab() {
    const box = $("#wbContent");
    // 按分组组织工具
    const groups = {};
    state.tools.forEach((t) => {
      const g = TOOL_GROUP[t.name] || "other";
      (groups[g] = groups[g] || []).push(t);
    });
    const groupOrder = ["load", "hygiene", "clean", "feature", "stats", "visual", "model", "report", "nl"];
    let html = '<div class="panel-card"><h3>分步分析工具</h3>';
    groupOrder.forEach((g) => {
      if (!groups[g]) return;
      html += `<div class="tool-group"><div class="tool-group-title">${esc(GROUP_NAME[g] || g)}</div><div class="tool-grid">`;
      groups[g].forEach((t) => {
        const label = esc(TOOL_LABEL[t.name] || t.name);
        const desc = esc(t.description || "");
        const hasParams = !!TOOL_PARAMS[t.name];
        html += `<div class="tool-card" data-tool="${esc(t.name)}">
          <button class="tool-btn${hasParams ? " has-params" : ""}" data-tool="${esc(t.name)}">
            <span class="t-name">${label}</span>
            <span class="t-desc">${desc}</span>
            ${hasParams ? '<span class="t-arrow">⚙</span>' : ''}
          </button>
          ${hasParams ? `<div class="tool-params" id="params-${esc(t.name)}" style="display:none"></div>` : ''}
        </div>`;
      });
      html += '</div></div>';
    });
    html += '</div>';
    box.innerHTML = html;

    // 绑定点击事件
    $$(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.tool;
        const paramsBox = $(`#params-${name}`);
        if (paramsBox && TOOL_PARAMS[name]) {
          // 切换参数面板显示
          const isVisible = paramsBox.style.display !== "none";
          $$(".tool-params").forEach((p) => (p.style.display = "none"));
          $$(".tool-btn").forEach((b) => b.classList.remove("expanded"));
          if (!isVisible) {
            renderToolParams(name, paramsBox);
            paramsBox.style.display = "block";
            btn.classList.add("expanded");
          }
        } else {
          // 无参数工具直接执行
          runTool(name, btn);
        }
      });
    });
  }

  function renderToolParams(toolName, container) {
    const params = TOOL_PARAMS[toolName] || [];
    let html = '<div class="param-form">';
    params.forEach((p) => {
      if (p.type === "select") {
        html += `<label class="param-item"><span class="param-label">${esc(p.label)}</span>
          <select id="param-${p.key}">
            ${p.options.map((o) => `<option value="${o}" ${o === p.default ? "selected" : ""}>${o}</option>`).join("")}
          </select></label>`;
      } else if (p.type === "checkbox") {
        html += `<label class="param-item checkbox"><input type="checkbox" id="param-${p.key}" ${p.default ? "checked" : ""}>
          <span class="param-label">${esc(p.label)}</span></label>`;
      } else {
        html += `<label class="param-item"><span class="param-label">${esc(p.label)}</span>
          <input id="param-${p.key}" type="text" value="${esc(String(p.default))}" placeholder="${esc(p.label)}"></label>`;
      }
    });
    html += `<button class="btn btn-primary btn-sm tool-run-btn" id="run-${toolName}">执行 ${esc(TOOL_LABEL[toolName] || toolName)}</button></div>`;
    container.innerHTML = html;
    $(`#run-${toolName}`).addEventListener("click", () => {
      const params = {};
      TOOL_PARAMS[toolName].forEach((p) => {
        const el = $(`#param-${p.key}`);
        if (p.type === "checkbox") params[p.key] = el.checked;
        else if (el.value && el.value !== p.default) params[p.key] = el.value;
      });
      runTool(toolName, $(`#run-${toolName}`), params);
    });
  }

  async function loadCharts() {
    const box = $("#wbContent");
    if (!state.runId) return;
    box.innerHTML = '<p class="muted">加载图表中…</p>';
    try {
      const r = await api(`/api/run/${state.runId}/charts`);
      if (!r.charts.length) { box.innerHTML = '<div class="empty"><div class="icon">▤</div><p>暂无图表，试试执行「可视化」工具</p></div>'; return; }
      box.innerHTML = '<div class="chart-grid">' + r.charts.map((c) => `
        <figure class="chart-card"><img src="${c.url}" alt="${esc(c.name)}"><figcaption>${esc(c.name)}</figcaption></figure>
      `).join("") + '</div>';
    } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  async function loadReport() {
    const box = $("#wbContent");
    if (!state.runId) return;
    box.innerHTML = '<p class="muted">加载报告中…</p>';
    try {
      const md = await fetch(`/api/report/${state.runId}`).then((r) => r.ok ? r.text() : null);
      if (!md) { box.innerHTML = '<div class="empty"><div class="icon">📝</div><p>暂无报告，试试执行「生成报告」或「全流程分析」</p></div>'; return; }
      box.innerHTML = `<div class="report-body">${esc(md).replace(/\n/g, "<br>")}</div>`;
      renderChatPanel(box, state.runId);
    } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  // -- 数据答疑对话面板（工作台报告页 / 全流程结果页共用） --
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
        // 规则作答时提示原因与解决办法（如 API 限额 / 配置缺失）
        if (!res.used_llm && res.reason) list.push({ role: "notice", text: res.reason });
      } catch (e) {
        list.push({ role: "assistant", text: "出错了：" + e.message });
      }
      renderChatMessages(runId, list, msgEl);
    };
    panel.querySelector(".chat-send").addEventListener("click", send);
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") send(); });
  }

  async function loadTrace() {
    const box = $("#wbContent");
    if (!state.runId) return;
    box.innerHTML = '<p class="muted">加载轨迹中…</p>';
    try {
      const r = await api(`/api/run/${state.runId}/trace`);
      let html = `<div class="panel-card"><h3>执行轨迹</h3>`;
      html += `<div class="trace-summary"><span>目标：<b>${esc(r.goal || "—")}</b></span><span>耗时：${r.duration != null ? Math.round(r.duration) + "s" : "—"}</span><span>节点：${r.node_count ?? "—"}</span></div>`;
      const events = r.events || [];
      if (!events.length) { html += '<p class="muted">暂无事件</p></div>'; box.innerHTML = html; return; }
      html += '<div class="trace-timeline">';
      events.forEach((e, i) => {
        const err = (e.event || "").includes("error") || e.error;
        html += `<div class="tl-item"><div class="tl-dot ${err ? "error" : ""}"></div>
          <div class="tl-content"><div class="tl-title">${esc(e.event || "step")}</div>
          <div class="tl-meta">#${i + 1}${e.duration_ms != null ? " · " + e.duration_ms + " ms" : ""}${e.error ? " · " + esc(e.error) : ""}</div></div></div>`;
      });
      html += '</div></div>';
      box.innerHTML = html;
    } catch (e) { box.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  function renderDownloads() {
    const box = $("#wbContent");
    if (!state.runId) { box.innerHTML = '<div class="empty"><p>无可用下载</p></div>'; return; }
    const id = state.runId;
    box.innerHTML = `<div class="panel-card"><h3>下载产物</h3><div class="dl-list">
      <a href="/api/run/${id}/download?name=report.md" download>下载报告 (.md) <span>→</span></a>
      <a href="/api/run/${id}/download?name=cleaned.csv" download>下载清洗后数据 (cleaned.csv) <span>→</span></a>
      <a href="/api/run/${id}/download?name=input.csv" download>下载原始数据 (input.csv) <span>→</span></a>
      <a href="/api/run/${id}/bundle" download>打包全部产物 (.zip) <span>→</span></a>
    </div></div>`;
  }

  // 会修改数据文件、需要立即回看数据的工具（执行后仍跳数据预览）
  const DATA_MUTATORS = ["data_clean", "feature_engineer"];

  async function runTool(name, btn, externalParams = {}) {
    if (!state.runId) { toast("请先选择运行", true); return; }
    const params = { ...externalParams };
    // 仅在没有外部参数时使用旧的默认逻辑（向后兼容）
    if (Object.keys(externalParams).length === 0) {
      if (name === "eda_plot") params.kind = "all";
      if (name === "data_clean") params.fill = "median";
      if (name === "nl_filter") params.question = "销售额最高的前10条";
      if (name === "nl_agg") params.question = "按地区汇总销售额";
      if (name === "nl_insight") params.question = "整体销售额表现如何";
    }
    btn?.classList.add("running");
    toast(`执行 ${TOOL_LABEL[name] || name} …`);
    try {
      const r = await api(`/api/run/${state.runId}/tool`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: name, params }),
      });
      toast(r.success ? "执行完成" : "执行失败", !r.success);
      // 侧边栏运行状态后台刷新（只写侧边栏，不覆盖主内容区）
      // 注意：不在此处调用 loadData/loadCharts/loadReport，它们会异步覆盖主内容，
      // 与下方工具结果渲染产生竞态；对应 tab 均为懒加载，切过去时自动刷新。
      loadRuns().catch(() => {});
      // 展示工具执行结果：清洗类回数据预览，其余展示真实结果
      const target = (r.success && !DATA_MUTATORS.includes(name)) ? "tool-result" : "data";
      if (r.success) state.toolResult = { tool: name, data: r };
      state.wbTab = target;
      $$("#wbTabs .toolbar-tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === target));
      renderWorkbenchContent();
    } catch (e) { toast(e.message, true); }
    finally { btn?.classList.remove("running"); }
  }

  async function loadTools() {
    try {
      const r = await api("/api/tools");
      state.tools = r.tools || [];
    } catch (e) { toast("加载工具失败", true); }
  }

  async function loadHistory() {
    /* 首次加载缓存， sidebar 打开时再渲染 */
  }

  /* ---- 全流程分析 ---- */
  function bindFlow() {
    const dz = $("#flowDropzone");
    const input = $("#flowFile");
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault(); dz.classList.remove("dragover");
      const f = e.dataTransfer.files[0];
      if (f) setFlowFile(f);
    });
    input.addEventListener("change", () => { if (input.files[0]) setFlowFile(input.files[0]); });

    $("#flowHelpBtn").addEventListener("click", openHelpModal);
    $("#helpCloseBtn").addEventListener("click", closeHelpModal);
    $("#helpModal").addEventListener("click", (e) => { if (e.target.id === "helpModal") closeHelpModal(); });
    $("#flowStartBtn").addEventListener("click", startFlow);

    // 目标模板 chips：点击即填入分析目标
    $$("#goalChips .chip").forEach((c) => c.addEventListener("click", () => setGoalChip(c)));

    $$("#flowResultTabs .result-tab").forEach((t) => t.addEventListener("click", () => {
      state.flowTab = t.dataset.tab;
      $$("#flowResultTabs .result-tab").forEach((x) => x.classList.toggle("active", x === t));
      renderFlowResult();
    }));
  }

  function setGoalChip(chip) {
    $("#flowGoal").value = chip.dataset.goal;
    $$("#goalChips .chip").forEach((x) => x.classList.remove("active"));
    $$("#goalSuggestChips .chip").forEach((x) => x.classList.remove("active"));
    chip.classList.add("active");
  }

  // 上传数据后基于数据推断可分析方向，展示为建议 chips（不阻塞主流程）
  async function loadGoalSuggest(rid) {
    try {
      const r = await api(`/api/run/${rid}/suggest-goals`);
      if (!(r.suggestions && r.suggestions.length)) return;
      const box = $("#goalSuggest");
      const c = $("#goalSuggestChips");
      c.innerHTML = r.suggestions.map((s) => `<span class="chip" data-goal="${esc(s)}">${esc(s)}</span>`).join("");
      c.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => setGoalChip(chip)));
      box.style.display = "block";
    } catch (e) { /* 建议拉取失败不影响分析主流程 */ }
  }

  function formatBytes(b) {
    if (!b) return "0 B";
    const k = 1024, s = ["B","KB","MB","GB"];
    const i = Math.min(s.length - 1, Math.floor(Math.log(b) / Math.log(k)));
    return (b / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1) + " " + s[i];
  }

  function openHelpModal() { $("#helpModal").classList.add("show"); }
  function closeHelpModal() { $("#helpModal").classList.remove("show"); }

  function setFlowFile(file) {
    state.flowFile = file;
    const dz = $("#flowDropzone");
    // 重置动画（每次选择文件都有一次高亮脉冲）
    dz.classList.remove("filled");
    void dz.offsetWidth;
    dz.classList.add("filled");
    // 更新上传后醒目的文件展示条
    const bar = $("#flowFileName");
    bar.style.display = "flex";
    bar.querySelector(".fs-name").textContent = file.name;
    bar.querySelector(".fs-size").textContent = formatBytes(file.size || 0);
    $("#flowFileNameHint").style.display = "none";
  }

  async function startFlow() {
    const file = state.flowFile;
    // 目标可选：不填则由后端使用默认目标（综合探索分析），不再强制要求
    const goal = $("#flowGoal").value.trim();
    if (!file) { toast("请先上传 CSV 文件", true); return; }
    $("#flowProgress").style.display = "block";
    resetFlowProgress();
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api("/api/run", { method: "POST", body: fd });
      state.flowRunId = r.run_id;
      await loadRuns();
      loadGoalSuggest(state.flowRunId); // 展示基于当前数据的分析建议
      runFlowAnalyze(goal);
    } catch (e) { flowError(e.message); }
  }

  async function runFlowAnalyze(goal) {
    try {
      const fd = new FormData();
      fd.append("goal", goal);
      await api(`/api/run/${state.flowRunId}/analyze?async_mode=true`, { method: "POST", body: fd });
      toast("全流程分析已开始");
      await pollFlow(goal);
    } catch (e) { flowError(e.message); }
  }

  function resetFlowProgress() {
    $$("#flowSteps .step").forEach((s) => s.className = "step");
    $("#flowProgressBar").style.width = "0%";
    $("#flowLogs").innerHTML = "";
    $("#flowResult").style.display = "none";
  }

  function flowLog(msg) {
    const box = $("#flowLogs");
    const div = document.createElement("div");
    div.className = "log";
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    box.prepend(div);
  }

  function setFlowStep(n, done = false) {
    $$("#flowSteps .step").forEach((s) => {
      const idx = parseInt(s.dataset.step, 10);
      s.classList.remove("active", "done");
      if (idx < n) s.classList.add("done");
      else if (idx === n) s.classList.add(done ? "done" : "active");
    });
    $("#flowProgressBar").style.width = Math.min((n / 5) * 100, 100) + "%";
  }

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  async function pollFlow(goal) {
    for (let i = 0; i < 300; i++) {
      await sleep(1000);
      let st;
      try { st = await api(`/api/run/${state.flowRunId}/progress`); } catch (e) { continue; }
      if (st.status === "running") {
        flowLog(st.stage || "分析中…");
        const stageMap = { "load": 1, "clean": 2, "feature": 2, "stats": 3, "visual": 4, "report": 5 };
        setFlowStep(stageMap[st.stage] || Math.min(1 + Math.floor(i / 20), 4));
        continue;
      }
      if (st.status === "done" || st.status === "failed") {
        setFlowStep(5, st.status === "done");
        const mode = st.mode === "llm" ? "LLM 自动编排" : "本地规则模式";
        toast(st.status === "done" ? `全流程分析完成（${mode}）` : `分析失败：${esc(st.error || "")}`, st.status !== "done");
        state.runId = state.flowRunId;
        await loadRuns();
        state.flowTab = "report";
        $$("#flowResultTabs .result-tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === "report"));
        $("#flowResult").style.display = "block";
        renderFlowResult();
        return;
      }
      break;
    }
  }

  function flowError(msg) {
    flowLog("错误：" + msg);
    toast(msg, true);
  }

  async function renderFlowResult() {
    const box = $("#flowResultBody");
    const id = state.flowRunId;
    if (!id) { box.innerHTML = '<p class="muted">无结果</p>'; return; }
    box.innerHTML = '<p class="muted">加载中…</p>';
    if (state.flowTab === "report") {
      try {
        const md = await fetch(`/api/report/${id}`).then((r) => r.ok ? r.text() : null);
        box.innerHTML = md ? `<div class="report-body">${esc(md).replace(/\n/g, "<br>")}</div>` : '<div class="empty">暂无报告</div>';
        if (md) renderChatPanel(box, id);
      } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
    } else if (state.flowTab === "charts") {
      try {
        const r = await api(`/api/run/${id}/charts`);
        if (!r.charts.length) { box.innerHTML = '<div class="empty">暂无图表</div>'; return; }
        box.innerHTML = '<div class="chart-grid">' + r.charts.map((c) => `<figure class="chart-card"><img src="${c.url}" alt="${esc(c.name)}"><figcaption>${esc(c.name)}</figcaption></figure>`).join("") + '</div>';
      } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
    } else if (state.flowTab === "trace") {
      try {
        const r = await api(`/api/run/${id}/trace`);
        const events = r.events || [];
        if (!events.length) { box.innerHTML = '<div class="empty">暂无轨迹</div>'; return; }
        box.innerHTML = '<div class="trace-timeline">' + events.map((e, i) => `
          <div class="tl-item"><div class="tl-dot ${(e.event || "").includes("error") || e.error ? "error" : ""}"></div>
          <div class="tl-content"><div class="tl-title">${esc(e.event || "step")}</div>
          <div class="tl-meta">#${i + 1}${e.duration_ms != null ? " · " + e.duration_ms + " ms" : ""}${e.error ? " · " + esc(e.error) : ""}</div></div></div>
        `).join("") + '</div>';
      } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
