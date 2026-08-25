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
    from scipy import stats as ss
    test_type = params.get("test_type")
    # chi2 检验作用于分类列，提前于数值列要求处理
    if test_type and test_type.lower() == "chi2":
        col = params.get("col")
        col2 = params.get("col2")
        if not col or col not in df.columns:
            return {"success": False, "error": f"column not found: {col}"}
        if not col2 or col2 not in df.columns:
            return {"success": False, "error": f"col2 column not found: {col2}"}
        ct = pd.crosstab(df[col], df[col2])
        if ct.size == 0:
            return {"success": False, "error": "empty contingency table"}
        chi2, p, dof, _expected = ss.chi2_contingency(ct)
        result = {"col": col, "col2": col2, "test_type": "chi2", "n": int(len(df)),
                  "chi2": {"statistic": _clean_res(float(chi2)), "p_value": _clean_res(float(p)),
                           "dof": int(dof), "significant": bool(p < 0.05)}}
        meta = ws.save_json(result, "stats_hyptest.json")
        return {"success": True, **result, "meta_file": meta}
    cols = _num_cols(df)
    if not cols:
        return {"success": False, "error": "no numeric column"}
    col = params.get("col") or cols[0]
    if col not in df.columns:
        return {"success": False, "error": f"column not found: {col}"}
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 8:
        return {"success": False, "error": "need >=8 numeric samples"}
    group_col = params.get("group")
    result = {"col": col, "n": int(len(vals))}
    # 向后兼容：未指定 test_type 时运行全部既有检验（正态 + t + anova）
    if not test_type:
        sample = vals.sample(min(len(vals), 2000), random_state=42)
        stat, pval = ss.shapiro(sample)
        result["shapiro"] = {"statistic": _clean_res(float(stat)), "p_value": _clean_res(float(pval)),
                             "normal": _clean_res(float(pval)) > 0.05}
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
    tt = test_type.lower()
    result["test_type"] = tt
    if tt == "normality":
        sample = vals.sample(min(len(vals), 2000), random_state=42)
        stat, pval = ss.shapiro(sample)
        result["shapiro"] = {"statistic": _clean_res(float(stat)), "p_value": _clean_res(float(pval)),
                            "normal": _clean_res(float(pval)) > 0.05}
    elif tt == "ttest":
        mu = _clean_res(float(vals.mean()))
        sample = vals.sample(min(len(vals), 2000), random_state=42)
        tstat, tval = ss.ttest_1samp(sample, 0.0)
        result["ttest_vs_zero"] = {"statistic": _clean_res(float(tstat)), "p_value": _clean_res(float(tval)),
                                  "mean": mu}
    elif tt == "anova":
        if not (group_col and group_col in df.columns):
            return {"success": False, "error": "anova requires 'group' column"}
        grouped = df[[group_col, col]].dropna()
        groups = [g[col].values for _, g in grouped.groupby(group_col) if len(g) >= 5]
        if len(groups) < 2:
            return {"success": False, "error": "need >=2 groups with >=5 samples each"}
        fstat, fval = ss.f_oneway(*groups)
        anova_res = {"group_by": group_col, "statistic": _clean_res(float(fstat)),
                     "p_value": _clean_res(float(fval)), "significant": bool(fval < 0.05)}
        # 显著时追加 Tukey HSD 事后检验
        if fval < 0.05:
            try:
                tukey = ss.tukey_hsd(*groups)
                group_names = [name for name, g in grouped.groupby(group_col) if len(g) >= 5]
                anova_res["tukey_hsd"] = {
                    "groups": [str(g) for g in group_names],
                    "statistic": _clean_res(tukey.statistic.tolist()),
                    "pvalue": _clean_res(tukey.pvalue.tolist()),
                }
            except Exception:
                anova_res["tukey_hsd"] = {"error": "tukey_hsd unavailable"}
        result["anova"] = anova_res
    elif tt == "wilcoxon":
        median = float(vals.median())
        try:
            wstat, wp = ss.wilcoxon(vals - median)
            result["wilcoxon"] = {"statistic": _clean_res(float(wstat)), "p_value": _clean_res(float(wp)),
                                  "median": _clean_res(median)}
        except Exception as e:
            result["wilcoxon"] = {"error": f"wilcoxon failed: {e}"}
    elif tt == "mannwhitney":
        if not (group_col and group_col in df.columns):
            return {"success": False, "error": "mannwhitney requires 'group' column"}
        grouped = df[[group_col, col]].dropna()
        groups = [g[col].values for _, g in grouped.groupby(group_col) if len(g) >= 5]
        if len(groups) < 2:
            return {"success": False, "error": "need >=2 groups with >=5 samples each"}
        ustat, up = ss.mannwhitneyu(groups[0], groups[1], alternative="two-sided")
        result["mannwhitney"] = {"group_by": group_col,
                                 "statistic": _clean_res(float(ustat)), "p_value": _clean_res(float(up))}
    elif tt == "ks":
        if not (group_col and group_col in df.columns):
            return {"success": False, "error": "ks requires 'group' column"}
        grouped = df[[group_col, col]].dropna()
        groups = [g[col].values for _, g in grouped.groupby(group_col) if len(g) >= 5]
        if len(groups) < 2:
            return {"success": False, "error": "need >=2 groups with >=5 samples each"}
        kstat, kp = ss.ks_2samp(groups[0], groups[1])
        result["ks"] = {"group_by": group_col,
                        "statistic": _clean_res(float(kstat)), "p_value": _clean_res(float(kp))}
    else:
        return {"success": False, "error": f"unknown test_type: {tt}"}
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
                # ADF 平稳性检验（H0：存在单位根，非平稳）
                try:
                    from statsmodels.tsa.stattools import adfuller
                    adf_res = adfuller(series.values, autolag="AIC")
                    out["adf"] = {"statistic": _clean_res(float(adf_res[0])),
                                  "p_value": _clean_res(float(adf_res[1])),
                                  "used_lag": int(adf_res[2]), "n_obs": int(adf_res[3]),
                                  "critical_values": _clean_res(dict(adf_res[4])),
                                  "stationary": bool(adf_res[1] < 0.05)}
                except Exception as e:
                    out["adf"] = {"error": f"adfuller failed: {e}"}
                # KPSS 平稳性检验（H0：平稳）
                try:
                    from statsmodels.tsa.stattools import kpss
                    kpss_res = kpss(series.values, regression="c", nlags="auto")
                    out["kpss"] = {"statistic": _clean_res(float(kpss_res[0])),
                                   "p_value": _clean_res(float(kpss_res[1])),
                                   "critical_values": _clean_res(dict(kpss_res[3])) if len(kpss_res) > 3 else None,
                                   "stationary": bool(kpss_res[1] > 0.05)}
                except Exception as e:
                    out["kpss"] = {"error": f"kpss failed: {e}"}
                # 季节分解（加法模型）
                try:
                    from statsmodels.tsa.seasonal import seasonal_decompose
                    period = min(12, max(2, len(series) // 2))
                    if len(series) >= 2 * period:
                        decomp = seasonal_decompose(series, period=period, model="additive")
                        trend_series = decomp.trend.dropna()
                        resid_series = decomp.resid.dropna()
                        out["decomposition"] = {
                            "period": int(period),
                            "trend_end": _clean_res(float(trend_series.iloc[-1])) if len(trend_series) else None,
                            "seasonal_mean": _clean_res(float(decomp.seasonal.dropna().mean())),
                            "resid_std": _clean_res(float(resid_series.std())) if len(resid_series) else None,
                        }
                    else:
                        out["decomposition"] = {"error": "not enough observations for decomposition"}
                except Exception as e:
                    out["decomposition"] = {"error": f"seasonal_decompose failed: {e}"}
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


def time_series_forecast(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cols = _num_cols(df)
    if not cols:
        return {"success": False, "error": "no numeric column"}
    val_col = params.get("col") or cols[0]
    if val_col not in df.columns:
        return {"success": False, "error": f"column not found: {val_col}"}
    # 自动查找日期列
    date_col = params.get("date")
    if not date_col:
        for c in df.columns:
            if c in cols:
                continue
            if "date" in c.lower() or "time" in c.lower():
                try:
                    pd.to_datetime(df[c], errors="raise")
                    date_col = c
                    break
                except Exception:
                    continue
        if not date_col:
            for c in df.columns:
                if c in cols:
                    continue
                try:
                    pd.to_datetime(df[c], errors="raise")
                    date_col = c
                    break
                except Exception:
                    continue
    if not date_col or date_col not in df.columns:
        return {"success": False, "error": "no parseable date column; specify 'date'"}
    try:
        ts = pd.to_datetime(df[date_col])
    except Exception:
        return {"success": False, "error": f"cannot parse {date_col} as datetime"}
    series = pd.Series(pd.to_numeric(df[val_col], errors="coerce").values, index=ts)
    series = series.sort_index().ffill().dropna()
    if len(series) < 8:
        return {"success": False, "error": "need >=8 time series points"}
    steps = max(1, min(int(params.get("steps", 10)), 30))
    method = (params.get("method") or "arima").lower()
    out = {"col": val_col, "date_col": date_col, "method": method, "steps": steps,
           "n_history": int(len(series)), "last_value": _clean_res(float(series.iloc[-1]))}
    # 推断频率并构造未来时间索引
    step = series.index[1] - series.index[0]
    inferred_freq = pd.infer_freq(series.index)
    try:
        if inferred_freq:
            forecast_idx = pd.date_range(start=series.index[-1] + step,
                                         periods=steps, freq=inferred_freq)
        else:
            forecast_idx = pd.date_range(start=series.index[-1] + step,
                                         periods=steps, freq=step)
    except Exception:
        forecast_idx = pd.RangeIndex(start=len(series), stop=len(series) + steps)
    forecast_vals = []
    ci_low = None
    ci_high = None
    if method == "arima":
        try:
            from statsmodels.tsa.arima.model import ARIMA
            best_aic = None
            best_order = None
            best_model = None
            # 自动选择 (p, d, q)：遍历组合取 AIC 最低者
            for p in range(3):
                for d in range(2):
                    for q in range(3):
                        try:
                            m = ARIMA(series, order=(p, d, q)).fit()
                            if best_aic is None or m.aic < best_aic:
                                best_aic = m.aic
                                best_order = (p, d, q)
                                best_model = m
                        except Exception:
                            continue
            if best_model is None:
                return {"success": False, "error": "ARIMA fitting failed for all (p,d,q)"}
            fc_res = best_model.get_forecast(steps=steps)
            fc_mean = fc_res.predicted_mean
            ci = fc_res.conf_int(alpha=0.05)
            forecast_vals = _clean_res(list(fc_mean.values))
            ci_low = _clean_res(list(ci.iloc[:, 0].values))
            ci_high = _clean_res(list(ci.iloc[:, 1].values))
            out["aic"] = _clean_res(float(best_aic))
            out["order"] = list(best_order)
        except Exception as e:
            return {"success": False, "error": f"ARIMA forecast failed: {e}"}
    elif method == "exponential":
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            m = ExponentialSmoothing(series, trend="add", seasonal=None).fit()
            fc = m.forecast(steps)
            forecast_vals = _clean_res(list(fc.values))
        except Exception as e:
            return {"success": False, "error": f"exponential forecast failed: {e}"}
    elif method == "naive":
        forecast_vals = [float(series.iloc[-1])] * steps
    else:
        return {"success": False, "error": f"unknown method: {method}"}
    out["forecast"] = forecast_vals
    if ci_low is not None:
        out["ci_low"] = ci_low
        out["ci_high"] = ci_high
    # 绘制历史 + 预测（含置信区间）
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(series.index, series.values, color="#4c8bf5", label="history")
    ax.plot(forecast_idx, forecast_vals, color="#e5532f", label="forecast")
    if ci_low is not None:
        ax.fill_between(forecast_idx, ci_low, ci_high, color="#e5532f", alpha=0.2, label="95% CI")
    ax.set_xlabel(date_col)
    ax.set_ylabel(val_col)
    ax.set_title(f"{val_col} 预测 ({method})")
    ax.legend()
    fig.tight_layout()
    img = ws.charts_dir / "forecast.png"
    fig.savefig(img, dpi=90)
    plt.close(fig)
    try:
        out["forecast_index"] = [str(x) for x in forecast_idx]
    except Exception:
        out["forecast_index"] = list(range(steps))
    out["chart"] = img.name
    meta = ws.save_json(out, "forecast.json")
    return {"success": True, **out, "meta_file": meta}


def ab_test(ws, params):
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    group_col = params.get("group_col")
    metric_col = params.get("metric_col")
    if not group_col or group_col not in df.columns:
        return {"success": False, "error": f"group_col not found: {group_col}"}
    if not metric_col or metric_col not in df.columns:
        return {"success": False, "error": f"metric_col not found: {metric_col}"}
    test = (params.get("test") or "ttest").lower()
    sub = df[[group_col, metric_col]].dropna()
    grouped = sub.groupby(group_col)
    group_keys = list(grouped.groups.keys())
    if len(group_keys) < 2:
        return {"success": False, "error": "need >=2 groups"}
    g1_name, g2_name = group_keys[0], group_keys[1]
    a = pd.to_numeric(grouped.get_group(g1_name)[metric_col], errors="coerce").dropna()
    b = pd.to_numeric(grouped.get_group(g2_name)[metric_col], errors="coerce").dropna()
    na, nb = len(a), len(b)
    out = {"group_col": group_col, "metric_col": metric_col, "test": test,
           "groups": {str(g1_name): {"n": int(na), "mean": _clean_res(float(a.mean())),
                                     "std": _clean_res(float(a.std(ddof=1))) if na > 1 else None},
                      str(g2_name): {"n": int(nb), "mean": _clean_res(float(b.mean())),
                                     "std": _clean_res(float(b.std(ddof=1))) if nb > 1 else None}}}
    # 每组均值的 95% 置信区间
    for name, g in [(g1_name, a), (g2_name, b)]:
        if len(g) > 1:
            se = float(g.std(ddof=1)) / np.sqrt(len(g))
            out["groups"][str(name)]["ci_95"] = _clean_res([float(g.mean()) - 1.96 * se,
                                                            float(g.mean()) + 1.96 * se])
    # Cohen's d 效应量（合并标准差）
    sa = float(a.std(ddof=1)) if na > 1 else 0.0
    sb = float(b.std(ddof=1)) if nb > 1 else 0.0
    pooled_std = np.sqrt(((na - 1) * sa ** 2 + (nb - 1) * sb ** 2) / max(na + nb - 2, 1)) if (na + nb) > 2 else 0.0
    cohens_d = (float(a.mean()) - float(b.mean())) / pooled_std if pooled_std else 0.0
    out["effect_size"] = {"cohens_d": _clean_res(float(cohens_d))}
    # 均值差的 95% 置信区间
    diff = float(a.mean()) - float(b.mean())
    se_diff = np.sqrt(sa ** 2 / max(na, 1) + sb ** 2 / max(nb, 1))
    out["mean_difference"] = {"diff": _clean_res(diff),
                              "ci_95": _clean_res([diff - 1.96 * se_diff, diff + 1.96 * se_diff])}
    from scipy import stats as ss
    if test == "ttest":
        # Welch's t-test（不假设方差齐性）
        tstat, tp = ss.ttest_ind(a, b, equal_var=False)
        out["result"] = {"statistic": _clean_res(float(tstat)), "p_value": _clean_res(float(tp)),
                         "significant": bool(tp < 0.05)}
    elif test == "mannwhitney":
        ustat, up = ss.mannwhitneyu(a, b, alternative="two-sided")
        out["result"] = {"statistic": _clean_res(float(ustat)), "p_value": _clean_res(float(up)),
                         "significant": bool(up < 0.05)}
    elif test == "proportion":
        # 将指标视为 0/1 二分类，做两比例 z 检验
        succ_a = int((a > 0).sum())
        succ_b = int((b > 0).sum())
        p_a = succ_a / na if na else 0.0
        p_b = succ_b / nb if nb else 0.0
        pooled_p = (succ_a + succ_b) / (na + nb) if (na + nb) else 0.0
        se_z = np.sqrt(pooled_p * (1 - pooled_p) * (1 / max(na, 1) + 1 / max(nb, 1))) if pooled_p not in (0, 1) else 0.0
        z = (p_a - p_b) / se_z if se_z else 0.0
        pval = 2 * (1 - ss.norm.cdf(abs(z))) if z else 1.0
        out["result"] = {"z_statistic": _clean_res(float(z)), "p_value": _clean_res(float(pval)),
                         "proportion_a": _clean_res(p_a), "proportion_b": _clean_res(p_b),
                         "successes_a": succ_a, "successes_b": succ_b,
                         "significant": bool(pval < 0.05)}
    else:
        return {"success": False, "error": f"unknown test: {test}"}
    meta = ws.save_json(out, "ab_test.json")
    return {"success": True, **out, "meta_file": meta}


def sample_size_calc(ws, params):
    try:
        from statsmodels.stats.power import tt_solve_power
    except ImportError:
        return {"success": False, "error": "statsmodels required for sample_size_calc"}
    try:
        effect_size = float(params.get("effect_size", 0.5))
    except (TypeError, ValueError):
        effect_size = 0.5
    try:
        alpha = float(params.get("alpha", 0.05))
    except (TypeError, ValueError):
        alpha = 0.05
    try:
        power = float(params.get("power", 0.8))
    except (TypeError, ValueError):
        power = 0.8
    n = tt_solve_power(effect_size=effect_size, alpha=alpha, power=power, alternative="two-sided")
    n_ceil = int(np.ceil(n))
    out = {"effect_size": _clean_res(effect_size), "alpha": _clean_res(alpha), "power": _clean_res(power),
           "sample_size_per_group": n_ceil, "raw_n": _clean_res(float(n))}
    meta = ws.save_json(out, "sample_size.json")
    return {"success": True, **out, "meta_file": meta}


class StatisticsServer(MCPServer):
    def __init__(self):
        super().__init__(name="statistics", description="深度统计分析")
        t = [
            ("corr_analysis", "计算相关性矩阵并生成热力图", ["ws", "cols"]),
            ("hypo_test", "假设检验: 正态性/t检验/ANOVA(含Tukey)/卡方/威尔科克森/Mann-Whitney/KS",
             ["ws", "col", "group", "test_type", "col2"]),
            ("regression_fit", "线性/多项式回归拟合，输出系数与 R²", ["ws", "feature", "target", "degree"]),
            ("time_series_feat", "时间序列趋势/波动特征、ADF/KPSS 平稳性与季节分解", ["ws", "date", "col"]),
            ("time_series_forecast", "时间序列预测(ARIMA自动定阶/指数平滑/朴素)与置信区间",
             ["ws", "date", "col", "method", "steps"]),
            ("cluster_profile", "K 均值聚类与簇画像", ["ws", "k"]),
            ("anomaly_detect", "Z-score 离群点识别", ["ws", "col", "threshold"]),
            ("dist_fit", "概率分布拟合(正态/对数正态/指数)与 KS 检验", ["ws", "col", "positive_only"]),
            ("pca_decompose", "主成分降维、载荷与方差解释", ["ws", "n_components"]),
        ]
        for name, desc, props in t:
            prop_schema = {"type": "object",
                           "properties": {p: {"type": "string"} for p in props}}
            # 用默认参数立即绑定当前迭代的函数，避免循环闭包把全部工具绑定到最后一个函数
            fn = globals()[name]
            self.register_tool(
                schema=ToolSchema(name=name, description=desc, parameters=prop_schema),
                handler=lambda fn=fn, **kw: fn(_resolve_ws(kw), kw),
            )
        # ab_test: 字符串参数 schema（group_col/metric_col/test）
        ab_schema = {
            "type": "object",
            "properties": {
                "group_col": {"type": "string"},
                "metric_col": {"type": "string"},
                "test": {"type": "string", "enum": ["ttest", "mannwhitney", "proportion"]},
            },
            "required": ["group_col", "metric_col"],
        }
        self.register_tool(
            schema=ToolSchema(name="ab_test",
                             description="A/B 测试: 分组描述统计、假设检验(Welch t/Mann-Whitney/比例 z)、Cohen's d 与均值差置信区间",
                             parameters=ab_schema),
            handler=lambda **kw: ab_test(_resolve_ws(kw), kw),
        )
        # sample_size_calc: 数值参数 schema（effect_size/alpha/power）
        ss_schema = {
            "type": "object",
            "properties": {
                "effect_size": {"type": "number", "default": 0.5},
                "alpha": {"type": "number", "default": 0.05},
                "power": {"type": "number", "default": 0.8},
            },
        }
        self.register_tool(
            schema=ToolSchema(name="sample_size_calc",
                             description="样本量计算: 基于 t 检验功效分析求解每组所需样本量",
                             parameters=ss_schema),
            handler=lambda **kw: sample_size_calc(_resolve_ws(kw), kw),
        )