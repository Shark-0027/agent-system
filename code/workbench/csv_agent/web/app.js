/* CSV 数据分析 Agent 工作台前端逻辑 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const state = { runId: "" };

  const TOOL_LABEL = {
    csv_load: "加载数据", data_summary: "数据概览", data_clean: "数据清洗",
    feature_engineer: "特征工程", eda_plot: "可视化", model_suggest: "模型建议",
    model_train: "模型训练", model_classify: "模型分类", report_generate: "生成报告",
    corr_analysis: "相关性热图", hypo_test: "假设检验", regression_fit: "回归拟合",
    time_series_feat: "时间序列", cluster_profile: "聚类分析", anomaly_detect: "离群点检测",
    dist_fit: "分布拟合", pca_decompose: "主成分分析", data_quality: "数据质量体检",
    nl_filter: "智能查数", nl_agg: "分组聚合", nl_insight: "智能洞察",
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
    return res.json();
  }

  async function init() {
    bindHealth();
    bindTabs();
    bindButtons();
    await loadTools();
    await loadRuns();
    loadHistory();
  }

  /* ---- 健康检查 + 运行模式 ---- */
  async function bindHealth() {
    try {
      const h = await api("/api/health");
      setHealth(true);
      setMode(h);
    }
    catch (e) { setHealth(false); }
  }
  function setHealth(ok) {
    $("#healthText").textContent = ok ? "服务正常" : "服务异常";
    $(".health .dot").className = "dot" + (ok ? " ok" : " err");
  }
  function setMode(h) {
    const el = $("#modeText");
    if (!el) return;
    if (h && h.mode) {
      el.textContent = h.mode_label || (h.mode === "llm" ? "LLM 模式" : "本地模式");
      el.className = "mode-badge mode-" + h.mode;
    } else {
      el.textContent = "";
      el.className = "mode-badge";
    }
  }

  /* ---- LLM 配置弹窗 ---- */
  function bindLlmConfig() {
    const modal = $("#llmModal");
    const status = $("#llmStatus");
    const showStatus = (msg, ok) => {
      status.textContent = msg;
      status.className = "info " + (ok ? "ok" : "err");
    };

    $("#llmConfigBtn").addEventListener("click", async () => {
      status.textContent = "";
      status.className = "info muted";
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
      modal.style.display = "flex";
    });

    $("#llmCloseBtn").addEventListener("click", () => (modal.style.display = "none"));
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });

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
          bindHealth(); // 刷新顶部运行模式徽标
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

  /* ---- 页签切换 ---- */
  function bindTabs() {
    $$(".tab").forEach((t) =>
      t.addEventListener("click", () => {
        $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
        $$(".tab-body").forEach((b) => (b.style.display = "none"));
        $("#tab-" + t.dataset.tab).style.display = "";
      }));
  }

  /* ---- 按钮绑定 ---- */
  function bindButtons() {
    $("#uploadBtn").addEventListener("click", uploadCsv);
    $("#sampleBtn").addEventListener("click", loadSample);
    $("#analyzeBtn").addEventListener("click", runAnalyze);
    $("#runsBtn").addEventListener("click", loadRuns);
    $("#refreshBtn").addEventListener("click", () => { bindHealth(); loadRuns(); loadTools(); });
    bindLlmConfig();
    $("#runSelect").addEventListener("change", onSelectRun);
  }

  function uploadBtn(busy) {
    $("#uploadBtn").disabled = busy;
    $("#sampleBtn").disabled = busy;
    $("#analyzeBtn").disabled = busy;
  }

  async function uploadCsv() {
    const file = $("#csvFile").files[0];
    if (!file) { toast("请先选择 CSV 文件", true); return; }
    const fd = new FormData();
    fd.append("file", file);
    uploadBtn(true);
    try {
      const r = await api("/api/run", { method: "POST", body: fd });
      state.runId = r.run_id;
      toast("上传成功：数据已预览");
      await loadRuns();
      selectRun(state.runId);
    } catch (e) { toast(e.message, true); }
    finally { uploadBtn(false); }
  }

  async function loadSample() {
    uploadBtn(true);
    try {
      const r = await api("/api/sample");
      state.runId = r.run_id;
      toast("已生成样例数据并预览");
      await loadRuns();
      selectRun(state.runId);
    } catch (e) { toast(e.message, true); }
    finally { uploadBtn(false); }
  }

  async function runAnalyze() {
    const file = $("#csvFile").files[0];
    const goal = $("#goal").value.trim();
    if (!file) { toast("请先选择 CSV 文件", true); return; }
    if (!goal) { toast("请填写分析目标", true); return; }
    const fd = new FormData();
    fd.append("goal", goal);
    fd.append("file", file);
    uploadBtn(true);
    try {
      const r = await api("/api/analyze", { method: "POST", body: fd });
      state.runId = r.run_id;
      toast(`全流程分析完成（${r.mode === "llm" ? "LLM 自动编排" : "本地规则模式"}）`);
      await loadRuns();
      selectRun(state.runId);
      showReportTab();
    } catch (e) { toast(e.message, true); }
    finally { uploadBtn(false); }
  }

  function showReportTab() {
    const tab = Array.from($$(".tab")).find((t) => t.dataset.tab === "report");
    if (tab) tab.click();
    loadReport();
  }

  /* ---- 运行列表 ---- */
  async function loadRuns() {
    try {
      const r = await api("/api/runs");
      const sel = $("#runSelect");
      const cur = sel.value;
      sel.innerHTML = '<option value="">— 请选择运行 —</option>';
      r.runs.forEach((x) => {
        const o = document.createElement("option");
        o.value = x.run_id;
        o.textContent = x.run_id + (x.has_report ? " · 有报告" : "");
        sel.appendChild(o);
      });
      if (cur && r.runs.some((x) => x.run_id === cur)) sel.value = cur;
      if (r.runs.length) {
        $("#runSelect").value = cur && r.runs.some((x)=>x.run_id===cur) ? cur : r.runs[0].run_id;
        onSelectRun();
      }
    } catch (e) { toast("加载运行列表失败", true); }
  }

  function selectRun(id) {
    $("#runSelect").value = id;
    state.runId = id;
    onSelectRun();
  }

  async function onSelectRun() {
    state.runId = $("#runSelect").value;
    if (!state.runId) {
      $("#runInfo").textContent = "选择运行后可查看/操作产物。";
      $("#tab-table").innerHTML = '<p class="muted">暂无数据。</p>';
      ["charts", "report", "download"].forEach((t) => $("#tab-" + t).innerHTML = `<p class="muted">暂无${t === "report" ? "报告" : t}。</p>`);
      return;
    }
    $("#runInfo").textContent = "加载运行信息…";
    await Promise.all([loadRunInfo(), loadData(), loadCharts(), loadReport(), loadingDownloads()]);
  }

  async function loadRunInfo() {
    if (!state.runId) return;
    try {
      const r = await api(`/api/run/${state.runId}/info`);
      $("#runInfo").innerHTML =
        `运行 <b>${r.run_id}</b>  |  报告 ${r.has_report ? "✅" : "❌"}  |  已清洗 ${r.has_cleaned ? "✅" : "❌"}`;
    } catch (e) { $("#runInfo").textContent = "加载信息失败"; }
  }

  /* ---- 数据表 ---- */
  async function loadData(which = "auto") {
    if (!state.runId) return;
    const id = state.runId;
    try {
      const r = await api(`/api/run/${id}/data?which=${which}`);
      let html = `<div class="table-wrap"><table class="data"><thead><tr>`;
      r.columns.forEach((c) => (html += `<th>${esc(c)}</th>`));
      html += `</tr></thead><tbody>`;
      r.sample.forEach((row) => {
        html += "<tr>";
        r.columns.forEach((c) => (html += `<td>${esc(String(row[c] ?? ""))}</td>`));
        html += "</tr>";
      });
      html += `</tbody></table></div><p class="muted">共 ${r.rows} 行 × ${r.cols} 列，预览前 10 行</p>`;
      $("#tab-table").innerHTML = html;
    } catch (e) { $("#tab-table").innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  /* ---- 图表 ---- */
  async function loadCharts() {
    if (!state.runId) return;
    const id = state.runId;
    try {
      const r = await api(`/api/run/${id}/charts`);
      if (!r.charts.length) { $("#tab-charts").innerHTML = '<p class="muted">暂无图表，试试运行“可视化”。</p>'; return; }
      $("#tab-charts").innerHTML = r.charts
        .map((c) => `<figure class="chart-item"><img src="${c.url}" alt="${esc(c.name)}"><figcaption>${esc(c.name)}</figcaption></figure>`)
        .join("<br>");
    } catch (e) { $("#tab-charts").innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  /* ---- 报告 ---- */
  async function loadReport() {
    if (!state.runId) return;
    const id = state.runId;
    try {
      const res = await fetch(`/api/report/${id}`);
      if (!res.ok) { $("#tab-report").innerHTML = '<p class="muted">暂无报告，试试“一键分析”或“生成报告”。</p>'; return; }
      const md = await res.text();
      $("#tab-report").innerHTML = `<div class="report-md">${esc(md).replace(/\n/g, "<br>")}</div>`;
    } catch (e) { $("#tab-report").innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`; }
  }

  /* ---- 下载 ---- */
  function loadingDownloads() {
    if (!state.runId) return;
    const id = state.runId;
    const base = `/api/run/${id}/download?name=`;
    const items = [
      ["下载报告 (.md)", "report.md"],
      ["下载清洗后数据 (cleaned.csv)", "cleaned.csv"],
      ["下载原始数据 (input.csv)", "input.csv"],
      ["打包全部产物 (.zip)", `bundle`],
    ];
    $("#tab-download").innerHTML = `<div class="dl-list">` + items
      .map(([label, name]) => name === "bundle"
        ? `<a href="/api/run/${id}/bundle" download>${label}</a>`
        : `<a href="${base}${name}" download>${label}</a>`)
      .join("") + `</div>`;
  }

  /* ---- 历史 ---- */
  async function loadHistory() {
    try {
      const r = await api("/api/history");
      if (!r.history.length) { $("#tab-history").innerHTML = '<p class="muted">暂无历史分析记录。</p>'; return; }
      $("#tab-history").innerHTML = r.history
        .map((h) => `<div class="info" style="border-bottom:1px solid var(--line);padding:6px 0;">
             <b>${esc(h.goal)}</b><br>
             <span class="muted">${esc(h.ts)}  ·列: ${esc(h.columns.join(", "))}  ·模型: ${esc(h.model || "—")}</span></div>`)
        .join("");
    } catch (e) { /* ignore */ }
  }

  /* ---- 工具 ---- */
  async function loadTools() {
    try {
      const r = await api("/api/tools");
      const box = $("#toolButtons");
      box.innerHTML = "";
      r.tools.forEach((t) => {
        const btn = document.createElement("button");
        btn.className = "btn primary";
        btn.textContent = TOOL_LABEL[t.name] || t.name;
        btn.title = t.description || t.name;
        btn.addEventListener("click", () => runTool(t.name, btn));
        box.appendChild(btn);
      });
    } catch (e) { $("#toolButtons").innerHTML = `<p class="muted">加载工具失败：${esc(e.message)}</p>`; }
  }

  async function runTool(name, btn) {
    if (!state.runId) { toast("请先选择运行", true); return; }
    const params = {};
    if (name === "eda_plot") params.kind = "all";
    if (name === "data_clean") params.fill = "median";
    if (name === "nl_filter") params.question = "销售额最高的前10条";
    if (name === "nl_agg") params.question = "按地区汇总销售额";
    if (name === "nl_insight") params.question = "整体销售额表现如何";
    btn.disabled = true;
    btn.classList.add("off");
    const out = $("#toolResult");
    out.className = "output";
    out.textContent = `执行 ${name} …`;
    try {
      const r = await api(`/api/run/${state.runId}/tool`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: name, params }),
      });
      out.className = "output " + (r.success ? "ok" : "err");
      out.textContent = JSON.stringify(r, null, 2);
      if (!r.success) toast("工具执行失败", true);
      await Promise.all([loadRunInfo(), loadData(), loadCharts(), loadReport()]);
    } catch (e) {
      out.className = "output err";
      out.textContent = e.message;
      toast(e.message, true);
    } finally {
      btn.disabled = false;
      btn.classList.remove("off");
    }
  }

  /* ---- 工具函数 ---- */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  document.addEventListener("DOMContentLoaded", init);
})();