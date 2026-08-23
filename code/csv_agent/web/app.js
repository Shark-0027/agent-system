/* CSV 数据分析 Agent 工作台前端逻辑 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const state = { runId: "" };

  const TOOL_LABEL = {
    csv_load: "加载数据", data_summary: "数据概览", data_clean: "数据清洗",
    feature_engineer: "特征工程", eda_plot: "可视化", model_suggest: "模型建议",
    model_train: "模型训练", report_generate: "生成报告",
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

  /* ---- 健康检查 ---- */
  async function bindHealth() {
    try { await api("/api/health"); setHealth(true); }
    catch (e) { setHealth(false); }
  }
  function setHealth(ok) {
    $("#healthText").textContent = ok ? "服务正常" : "服务异常";
    $(".health .dot").className = "dot" + (ok ? " ok" : " err");
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
      toast("全流程分析完成");
      await loadRuns();
      selectRun(state.runId);
      showReport();
    } catch (e) { toast(e.message, true); }
    finally { uploadBtn(false); }
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
    ];
    $("#tab-download").innerHTML = `<div class="dl-list">` + items
      .map(([label, name]) => `<a href="${base}${name}" download>${label}</a>`)
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