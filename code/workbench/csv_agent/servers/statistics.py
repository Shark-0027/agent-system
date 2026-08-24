from __future__ import annotations
import os
import tempfile
from typing import Any, Dict
# 强制 matplotlib 缓存指向可写临时目录，避免沙箱报错
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.visualizer import _setup_cjk_font
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

_setup_cjk_font()
plt.rcParams["axes.unicode_minus"] = False


def _load_df(ws) -> pd.DataFrame:
    path = ws.root / "cleaned.csv"
    if not path.exists():
        path = ws.root / "input.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def _num_cols(df: pd.DataFrame):
    return list(df.select_dtypes(include="number").columns)


def _clean_res(v) -> Any:
    """把 numpy 标量归一化为 JSON 安全值。"""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if (v != v or v in (float("inf"), float("-inf"))) else float(v)
    if isinstance(v, np.ndarray):
        return [_clean_res(x) for x in v]
    if isinstance(v, tuple):
        return [_clean_res(x) for x in v]
    return v


def corr_analysis(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if len(cols) < 2:
        return {"success": False, "error": "need at least 2 numeric columns"}
    corr = df[cols].corr()
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr.values, cmap="coolwarm", aspect="auto")
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, rotation=45, ha="right")
    ax.set_yticks(range(len(cols))); ax.set_yticklabels(cols)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im); fig.tight_layout()
    p = ws.charts_dir / "corr_heatmap.png"
    fig.savefig(p, dpi=90); plt.close(fig)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append({"a": cols[i], "b": cols[j], "pearson": _clean_res(float(corr.values[i, j]))})
    pairs.sort(key=lambda x: abs(x["pearson"]), reverse=True)
    meta = ws.save_json({"pairs": pairs, "chart": "corr_heatmap.png"}, "stats_corr.json")
    return {"success": True, "top_pairs": pairs[:5], "chart": p.name, "meta_file": meta}


def hypo_test(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if not cols:
        return {"success": False, "error": "no numeric column"}
    from scipy import stats as ss
    col = params.get("col") or cols[0]
    if col not in df.columns:
        return {"success": False, "error": f"column not found: {col}"}
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 8:
        return {"success": False, "error": "need >=8 numeric samples"}
    group_col = params.get("group")
    result = {"col": col, "n": int(len(vals))}
    # 正态性检验（Shapiro，样本过大时截断）
    sample = vals.sample(min(len(vals), 2000), random_state=42)
    stat, pval = ss.shapiro(sample)
    result["shapiro"] = {"statistic": _clean_res(float(stat)), "p_value": _clean_res(float(pval)),
                         "normal": _clean_res(float(pval)) > 0.05}
    # 单样本 t 检验 vs 0（或指定值）
    mu = _clean_res(float(vals.mean()))
    tstat, tval = ss.ttest_1samp(sample, 0.0)
    result["ttest_vs_zero"] = {"statistic": _clean_res(float(tstat)), "p_value": _clean_res(float(tval)),
                               "mean": mu}
    if group_col and group_col in df.columns:
        grouped = df[[group_col, col]].dropna()
        groups = [g[col].values for _, g in grouped.groupby(group_col) if len(g) >= 5]
        if len(groups) >= 2:
            fstat, fval = ss.f_oneway(*groups)
            result["anova"] = {"group_by": group_col, "statistic": _clean_res(float(fstat)),
                               "p_value": _clean_res(float(fval))}
    meta = ws.save_json(result, "stats_hyptest.json")
    return {"success": True, **result, "meta_file": meta}


def regression_fit(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    y_col = params.get("target") or (cols[1] if len(cols) >= 2 else (cols[0] if cols else ""))
    x_col = params.get("feature")
    if y_col not in df.columns:
        return {"success": False, "error": f"target column not found: {y_col}"}
    if x_col is None or x_col not in df.columns:
        x_col = cols[0] if cols and cols[0] != y_col else (cols[1] if len(cols) >= 2 else None)
    if not x_col:
        return {"success": False, "error": "need an independent numeric column"}
    sub = df[[x_col, y_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) < 10:
        return {"success": False, "error": "need >=10 paired samples"}
    x = sub[x_col].values
    y = sub[y_col].values
    degree = max(1, min(int(params.get("degree", 1)), 3))
    coefs = np.polyfit(x, y, degree)
    p = np.poly1d(coefs)
    y_hat = p(x)
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0.0
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(x, y, s=18, alpha=0.6, color="#4c8bf5")
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, p(xs), color="#e5532f", lw=2)
    ax.set_xlabel(x_col); ax.set_ylabel(y_col)
    ax.set_title(f"{x_col} ~ {y_col} (R²={r2:.3f})")
    fig.tight_layout()
    img = ws.charts_dir / "regression_fit.png"
    fig.savefig(img, dpi=90); plt.close(fig)
    result = {"x": x_col, "target": y_col, "degree": degree,
              "coeffs": _clean_res(list(coefs)), "r2": _clean_res(float(r2)),
              "n": int(len(sub)), "chart": img.name}
    meta = ws.save_json(result, "stats_regression.json")
    return {"success": True, **result, "meta_file": meta}


def _group_key(col):
    try:
        return col._short_name
    except AttributeError:
        return str(col)


def time_series_feat(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if not cols:
        return {"success": False, "error": "no numeric column"}
    date_col = params.get("date")
    val_col = params.get("col") or cols[0]
    if val_col not in df.columns:
        return {"success": False, "error": f"column not found: {val_col}"}
    if date_col and date_col in df.columns:
        try:
            ts = pd.to_datetime(df[date_col])
        except Exception:
            ts = None
        if ts is not None:
            series = pd.Series(pd.to_numeric(df[val_col], errors="coerce").values, index=ts)
            series = series.sort_index().ffill().dropna()
            if len(series) >= 4:
                trend_end = series.iloc[-1] - series.iloc[0]
                mean = series.mean()
                cv = series.std() / abs(mean) if mean else None
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.plot(series.index, series.values, color="#4c8bf5")
                ax.set_title(f"{val_col} 时间序列")
                fig.tight_layout()
                img = ws.charts_dir / "trend.png"
                fig.savefig(img, dpi=90); plt.close(fig)
                out = {"col": val_col, "date_col": date_col, "points": int(len(series)),
                       "trend_end_delta": _clean_res(float(trend_end)), "mean": _clean_res(float(mean)),
                       "cv": _clean_res(float(cv)) if cv is not None else None,
                       "min": _clean_res(float(series.min())), "max": _clean_res(float(series.max())),
                       "chart": img.name}
                meta = ws.save_json(out, "stats_timeseries.json")
                return {"success": True, **out, "meta_file": meta}
    vals = pd.to_numeric(df[val_col], errors="coerce").dropna()
    out = {"col": val_col, "error": "no parseable date column; basic stats only",
           "n": int(len(vals)), "mean": _clean_res(float(vals.mean())),
           "std": _clean_res(float(vals.std()))}
    meta = ws.save_json(out, "stats_timeseries.json")
    return {"success": True, **out, "meta_file": meta}


def cluster_profile(ws, params):
    from sklearn.cluster import KMeans
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if len(cols) < 2:
        return {"success": False, "error": "need >=2 numeric columns"}
    k = min(max(int(params.get("k", 3)), 2), 8)
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) < k:
        return {"success": False, "error": "too few rows for clustering"}
    X = (sub - sub.mean()) / sub.std().replace(0, 1)
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
    labels = km.labels_
    centers = pd.DataFrame(X, columns=cols)
    centers["cluster"] = labels
    profiles = centers.groupby("cluster").mean().round(4).to_dict(orient="index")
    counts = {int(i): int((labels == i).sum()) for i in range(k)}
    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        pca = __import__("sklearn.decomposition", fromlist=["PCA"]).PCA(n_components=2).fit_transform(X)
        ax.scatter(pca[:, 0], pca[:, 1], c=labels, cmap="Set2", s=20, alpha=0.7)
        ax.set_title(f"K 均值聚类 (k={k})")
    except Exception:
        ax.set_title(f"K 均值聚类 (k={k})")
    fig.tight_layout()
    img = ws.charts_dir / "cluster.png"
    fig.savefig(img, dpi=90); plt.close(fig)
    out = {"k": k, "n": int(len(sub)), "counts": counts, "profiles": _clean_res(profiles),
           "chart": img.name, "used_cols": cols}
    meta = ws.save_json(out, "stats_cluster.json")
    return {"success": True, **out, "meta_file": meta}


def anomaly_detect(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if not cols:
        return {"success": False, "error": "no numeric column"}
    col = params.get("col") or cols[0]
    if col not in df.columns:
        return {"success": False, "error": f"column not found: {col}"}
    vals = pd.to_numeric(df[col], errors="coerce")
    threshold = float(params.get("threshold", 3.0))
    mean, std = vals.mean(), vals.std()
    z = (vals - mean) / std if std else pd.Series(0.0, index=vals.index)
    is_out = z.abs() > threshold
    outliers = [{"index": int(i), "value": _clean_res(float(v))}
                for i, v, flag in zip(vals.index, vals, is_out) if flag]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(vals.index, vals.values, color="#4c8bf5", lw=1)
    bad_idx = [o["index"] for o in outliers]
    if bad_idx:
        ax.scatter(bad_idx, vals.iloc[bad_idx].values, color="#e5532f", s=30, zorder=3)
    ax.axhline(float(mean + threshold * std), color="#aaa", ls="--", lw=1)
    ax.axhline(float(mean - threshold * std), color="#aaa", ls="--", lw=1)
    ax.set_title(f"{col} 离群点检测 (z>{threshold})")
    fig.tight_layout()
    img = ws.charts_dir / "outliers.png"
    fig.savefig(img, dpi=90); plt.close(fig)
    out = {"col": col, "threshold": threshold, "n": int(len(vals)),
           "outlier_count": len(outliers), "outliers": outliers[:50], "chart": img.name}
    meta = ws.save_json(out, "stats_anomaly.json")
    return {"success": True, **out, "meta_file": meta}


def dist_fit(ws, params):
    try:
        from scipy import stats as ss
    except ImportError:
        return {"success": False, "error": "scipy required for dist_fit"}
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    col = params.get("col") or (cols[0] if cols else "")
    if col not in df.columns:
        return {"success": False, "error": f"column not found: {col}"}
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    vals = vals[vals > 0] if params.get("positive_only") else vals
    if len(vals) < 20:
        return {"success": False, "error": "need >=20 numeric samples"}
    v = vals.values
    results = []
    # 皮尔逊相关系数作为分布贴合度的粗略代理（正态）
    from scipy.stats import probplot
    _ = probplot(v, dist="norm")
    candidates = [("normal", "norm"), ("lognormal", "lognorm"), ("exponential", "expon")]
    best = None
    for name, dist in candidates:
        try:
            fitted = getattr(ss, dist).fit(v)
            pval = ss.kstest(v, dist, args=fitted).pvalue
            entry = {"dist": name, "p_value": _clean_res(float(pval)),
                     "ks_statistic": _clean_res(float(ss.kstest(v, dist, args=fitted).statistic)),
                     "params": _clean_res([float(x) for x in fitted])}
            results.append(entry)
            if best is None or pval > best["p_value"]:
                best = entry
        except Exception:  # noqa: BLE001 某些分布拟合失败时跳过
            continue
    if not results:
        return {"success": False, "error": "no distribution could be fitted"}
    results.sort(key=lambda r: r["p_value"], reverse=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    n, bins, _ = ax.hist(v, bins=30, density=True, alpha=0.6, color="#4c8bf5", edgecolor="white")
    xs = np.linspace(v.min(), v.max(), 300)
    _DIST_FUNC = {"normal": "norm", "lognormal": "lognorm", "exponential": "expon"}
    fitted = getattr(ss, _DIST_FUNC[results[0]["dist"]])
    pdf = fitted.pdf(xs, *results[0]["params"])
    ax.plot(xs, pdf, color="#e5532f", lw=2)
    ax.set_title(f"{col} 分布拟合 (最优: {results[0]['dist']})")
    fig.tight_layout()
    img = ws.charts_dir / "dist_fit.png"
    fig.savefig(img, dpi=90); plt.close(fig)
    out = {"col": col, "results": results, "best": results[0]["dist"],
           "chart": img.name}
    meta = ws.save_json(out, "stats_distfit.json")
    return {"success": True, **out, "meta_file": meta}


def pca_decompose(ws, params):
    from sklearn.decomposition import PCA
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if len(cols) < 2:
        return {"success": False, "error": "need >=2 numeric columns"}
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    X = (sub - sub.mean()) / sub.std().replace(0, 1)
    n_comp = min(len(cols), int(params.get("n_components", 2)))
    pca = PCA(n_components=n_comp).fit(X)
    exp = pca.explained_variance_ratio_
    scores = pca.transform(X)
    loadings = {cols[i]: _clean_res([float(x) for x in pca.components_[:, i]]) for i in range(len(cols))}
    out = {"n_components": n_comp, "explained_variance_ratio": _clean_res(list(exp)),
           "cumulative": _clean_res(float(exp.cumsum()[-1])), "loadings": loadings, "used_cols": cols}
    if n_comp >= 2:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.scatter(scores[:, 0], scores[:, 1], s=18, alpha=0.6, color="#4c8bf5")
        ax.set_xlabel(f"PC1 ({exp[0]:.0%})"); ax.set_ylabel(f"PC2 ({exp[1]:.0%})")
        ax.set_title("主成分投影")
        fig.tight_layout()
        img = ws.charts_dir / "pca.png"
        fig.savefig(img, dpi=90); plt.close(fig)
        out["chart"] = img.name
    meta = ws.save_json(out, "stats_pca.json")
    return {"success": True, **out, "meta_file": meta}


class StatisticsServer(MCPServer):
    def __init__(self):
        super().__init__(name="statistics", description="深度统计分析")
        t = [
            ("corr_analysis", "计算相关性矩阵并生成热力图", ["ws", "cols"]),
            ("hypo_test", "正态性/单样本 t 检验/组间 ANOVA 检验", ["ws", "col", "group"]),
            ("regression_fit", "线性/多项式回归拟合，输出系数与 R²", ["ws", "feature", "target", "degree"]),
            ("time_series_feat", "时间序列趋势/波动特征与曲线图", ["ws", "date", "col"]),
            ("cluster_profile", "K 均值聚类与簇画像", ["ws", "k"]),
            ("anomaly_detect", "Z-score 离群点识别", ["ws", "col", "threshold"]),
            ("dist_fit", "概率分布拟合(正态/对数正态/指数)与 KS 检验", ["ws", "col", "positive_only"]),
            ("pca_decompose", "主成分降维、载荷与方差解释", ["ws", "n_components"]),
        ]
        for name, desc, props in t:
            prop_schema = {"type": "object",
                           "properties": {p: {"type": "string"} for p in props}}
            handler = globals()[name]
            self.register_tool(
                schema=ToolSchema(name=name, description=desc, parameters=prop_schema),
                handler=lambda **kw: globals()[name](_resolve_ws(kw), kw),
            )