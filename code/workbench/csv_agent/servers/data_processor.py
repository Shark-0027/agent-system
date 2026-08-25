from __future__ import annotations
from typing import Any, Dict
import os
import tempfile
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

def data_clean(ws, params):
    init = ws.root / "input.csv"
    if not init.exists():
        return {"success": False, "error": "input.csv not found"}
    df = pd.read_csv(init)
    fill = params.get("fill", "median")
    strategy = params.get("strategy", "simple")
    outlier_method = params.get("outlier_method", "iqr")
    group_col = params.get("group_col")
    records = {"filled": [], "clipped": [], "flagged": []}
    missing_before = {c: int(df[c].isna().sum()) for c in df.columns}
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in df.columns if c not in num_cols]
    # 缺失值填充
    if any(missing_before.values()):
        if strategy == "knn":
            from sklearn.impute import KNNImputer
            if num_cols:
                imputer = KNNImputer(n_neighbors=5)
                df[num_cols] = imputer.fit_transform(df[num_cols])
                for c in num_cols:
                    if missing_before[c]:
                        records["filled"].append({"col": c, "n": missing_before[c], "method": "knn"})
            for c in cat_cols:
                if missing_before[c]:
                    mode = df[c].mode()
                    df[c] = df[c].fillna(mode.iloc[0] if not mode.empty else "未知")
                    records["filled"].append({"col": c, "n": missing_before[c], "method": "mode"})
        elif strategy == "group":
            if not group_col or group_col not in df.columns:
                return {"success": False, "error": "group strategy requires valid group_col"}
            for c in num_cols:
                if missing_before[c]:
                    df[c] = df.groupby(group_col)[c].transform(lambda x: x.fillna(x.median()))
                    if df[c].isna().any():
                        df[c] = df[c].fillna(df[c].median())
                    records["filled"].append({"col": c, "n": missing_before[c], "method": "group_median", "group_col": group_col})
            for c in cat_cols:
                if missing_before[c]:
                    mode = df[c].mode()
                    df[c] = df[c].fillna(mode.iloc[0] if not mode.empty else "未知")
                    records["filled"].append({"col": c, "n": missing_before[c], "method": "mode"})
        else:  # simple (默认，向后兼容)
            for c in df.columns:
                missing = missing_before[c]
                if missing == 0:
                    continue
                if pd.api.types.is_numeric_dtype(df[c]):
                    val = df[c].median() if fill == "median" else df[c].mean()
                    df[c] = df[c].fillna(val)
                    records["filled"].append({"col": c, "n": missing, "method": fill})
                else:
                    mode = df[c].mode()
                    df[c] = df[c].fillna(mode.iloc[0] if not mode.empty else "未知")
                    records["filled"].append({"col": c, "n": missing, "method": "mode"})
    # 异常值处理
    if outlier_method == "iqr":
        for c in num_cols:
            q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
            nlo = int((df[c] < lo).sum()); nhi = int((df[c] > hi).sum())
            if pd.notna(lo) and pd.notna(hi) and (nlo + nhi) > 0:
                df[c] = df[c].clip(lo, hi)
                records["clipped"].append({"col": c, "n": nlo + nhi, "method": "iqr"})
    elif outlier_method == "zscore":
        for c in num_cols:
            mean, std = df[c].mean(), df[c].std()
            if std and not df[c].isna().all():
                lo, hi = mean - 3 * std, mean + 3 * std
                nlo = int((df[c] < lo).sum()); nhi = int((df[c] > hi).sum())
                if nlo + nhi > 0:
                    df[c] = df[c].clip(lo, hi)
                    records["clipped"].append({"col": c, "n": nlo + nhi, "method": "zscore"})
    elif outlier_method == "isoforest":
        from sklearn.ensemble import IsolationForest
        if num_cols:
            clean = df[num_cols].dropna()
            if len(clean) > 1:
                iso = IsolationForest(contamination=0.05, random_state=42)
                pred = iso.fit_predict(clean)
                anom_idx = clean.index[pred == -1]
                df = df.drop(index=anom_idx)
                records["clipped"].append({"col": "__rows__", "n": int(len(anom_idx)), "method": "isoforest"})
    elif outlier_method == "mark":
        for c in num_cols:
            q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
            if pd.notna(lo) and pd.notna(hi):
                flag = ((df[c] < lo) | (df[c] > hi)).astype(int)
                if int(flag.sum()) > 0:
                    df[f"{c}_outlier"] = flag
                    records["flagged"].append({"col": c, "n": int(flag.sum()), "method": "iqr_mark"})
    df = df.drop_duplicates()
    ws.save_csv(df, "cleaned.csv")
    records["rows_after"] = int(len(df))
    records["dups_removed"] = int(len(pd.read_csv(init)) - len(df))
    return {"success": True, **records}

def feature_engineer(ws, params):
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    created = []
    if params.get("encode", True):
        for c in df.select_dtypes(include="object").columns:
            df[f"{c}_code"] = df[c].astype("category").cat.codes
            created.append(f"{c}_code")
            df = df.drop(columns=[c])
    if params.get("scale", True):
        for c in df.select_dtypes(include="number").columns:
            if c.endswith("_scaled"):
                continue
            s = df[c]
            if s.std() == 0 or s.isna().all():
                continue
            df[f"{c}_scaled"] = (s - s.mean()) / s.std()
            created.append(f"{c}_scaled")
    if params.get("interaction", False):
        nc = [c for c in df.select_dtypes(include="number").columns if not c.endswith("_scaled")]
        for i in range(len(nc)):
            for j in range(i + 1, len(nc)):
                a, b = nc[i], nc[j]
                name = f"{a}_x_{b}"
                df[name] = df[a] * df[b]
                created.append(name)
    if params.get("binning", False):
        for c in list(df.select_dtypes(include="number").columns):
            if c.endswith("_scaled") or c.endswith("_outlier") or c.endswith("_bin"):
                continue
            if df[c].nunique() > 10:
                df[f"{c}_bin"] = pd.cut(df[c], bins=5, labels=False)
                created.append(f"{c}_bin")
    if params.get("datetime_feat", False):
        for c in list(df.columns):
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                dt = df[c]
            else:
                dt = pd.to_datetime(df[c], errors="coerce")
                if dt.notna().sum() == 0 or dt.notna().sum() / max(len(dt), 1) <= 0.5:
                    continue
            df[f"{c}_year"] = dt.dt.year
            df[f"{c}_month"] = dt.dt.month
            df[f"{c}_dayofweek"] = dt.dt.dayofweek
            created.extend([f"{c}_year", f"{c}_month", f"{c}_dayofweek"])
    ws.save_csv(df, "cleaned.csv")
    return {"success": True, "features_added": created}

def feature_select(ws, params):
    """特征选择：VIF 递归剔除多重共线性 / 互信息保留 top half / RFE 包装法。"""
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    method = params.get("method", "vif")
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return {"success": False, "error": "need at least 2 numeric features"}
    target = params.get("target")
    if target is None:
        target = df.columns[-1]
    selected = list(numeric.columns)
    removed = []
    if method == "vif":
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        work = list(selected)
        while len(work) > 1:
            X = df[work].dropna()
            if len(X) < 2 or X.shape[1] < 2:
                break
            try:
                vifs = {c: float(variance_inflation_factor(X.values, i)) for i, c in enumerate(work)}
            except Exception:
                break
            worst = max(vifs, key=vifs.get)
            if vifs[worst] > 10:
                work.remove(worst)
                removed.append({"col": worst, "vif": vifs[worst]})
            else:
                break
        selected = work
    elif method == "mutual_info":
        from sklearn.feature_selection import mutual_info_regression
        if target not in df.columns:
            return {"success": False, "error": f"target {target} not found"}
        y = df[target]
        X = df[selected].dropna()
        y = y.loc[X.index]
        mi = mutual_info_regression(X, y)
        order = sorted(zip(selected, mi), key=lambda x: x[1], reverse=True)
        keep_n = max(1, len(order) // 2)
        selected = [c for c, _ in order[:keep_n]]
        removed = [{"col": c, "mi": float(m)} for c, m in order[keep_n:]]
    elif method == "rfe":
        from sklearn.feature_selection import RFE
        from sklearn.ensemble import RandomForestRegressor
        if target not in df.columns:
            return {"success": False, "error": f"target {target} not found"}
        X = df[selected].dropna()
        y = df[target].loc[X.index]
        n = max(1, len(selected) // 2)
        rfe = RFE(RandomForestRegressor(n_estimators=100, random_state=42), n_features_to_select=n)
        rfe.fit(X, y)
        keep_mask = list(rfe.get_support())
        selected = [c for c, k in zip(selected, keep_mask) if k]
        removed = [{"col": c, "rank": int(r)} for c, r in zip(df.select_dtypes(include="number").columns, rfe.ranking_) if c not in selected]
    else:
        return {"success": False, "error": f"unknown method {method}"}
    rest = [c for c in df.columns if c not in selected and c != target]
    tail = [target] if target in df.columns and target not in selected else []
    out = df[selected + rest + tail]
    ws.save_csv(out, "cleaned.csv")
    meta = {"method": method, "selected": selected, "removed": removed, "target": target}
    ws.save_json(meta, "feature_selected.json")
    return {"success": True, **meta, "meta_file": str(ws.root / "feature_selected.json")}

def data_quality(ws, params):
    """数据质量体检：缺失/重复/唯一性/异常比例，产出可查看报告。"""
    path = ws.root / ("cleaned.csv" if (ws.root / "cleaned.csv").exists() else "input.csv")
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    dups = int(df.duplicated().sum())
    total = int(len(df))
    cols_report = {}
    for c in df.columns:
        n_missing = int(df[c].isna().sum())
        n_unique = int(df[c].nunique())
        entry = {"missing": n_missing, "missing_pct": round(n_missing / total, 4) if total else 0.0,
                 "unique": n_unique, "unique_pct": round(n_unique / total, 4) if total else 0.0,
                 "dtype": str(df[c].dtype)}
        if pd.api.types.is_numeric_dtype(df[c]):
            v = pd.to_numeric(df[c], errors="coerce")
            mean, std = v.mean(), v.std()
            if std:
                outliers = int(((v - mean).abs() > 3 * std).sum())
                entry["outlier_count"] = outliers
                entry["outlier_pct"] = round(outliers / total, 4) if total else 0.0
        cols_report[c] = entry
    issues = []
    if dups:
        issues.append(f"发现 {dups} 行重复，建议去重")
    for c, r in cols_report.items():
        if r["missing_pct"] > 0.2:
            issues.append(f"列 {c} 缺失率 {r['missing_pct']:.0%}，建议处理")
        if r.get("outlier_pct", 0) > 0.03:
            issues.append(f"列 {c} 离群点占比 {r['outlier_pct']:.1%}(±3σ)")
    score = round(max(0.0, 100 - dups * 2 - sum(
        (c["missing_pct"] > 0.2) * 15 + min((c.get("outlier_pct", 0)) * 100, 15)
        for c in cols_report.values())), 1)
    report = {"rows": total, "cols": int(len(df.columns)),
              "duplicates": {"count": dups, "pct": round(dups / total, 4) if total else 0.0},
              "columns": cols_report, "score": score, "issues": issues}
    ws.save_json(report, "data_quality.json")
    return {"success": True, **report, "meta_file": str(ws.root / "data_quality.json")}

def missing_pattern(ws, params):
    """缺失模式分析：缺失率、共现矩阵、MCAR t 检验与热力图。"""
    from scipy import stats
    path = ws.root / ("cleaned.csv" if (ws.root / "cleaned.csv").exists() else "input.csv")
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    total = len(df)
    cols = list(df.columns)
    na_masks = {c: df[c].isna() for c in cols}
    miss_rate = {c: round(int(na_masks[c].sum()) / total, 4) if total else 0.0 for c in cols}
    # 共现矩阵
    cooc = {}
    for i, c1 in enumerate(cols):
        for c2 in cols[i:]:
            both = int((na_masks[c1] & na_masks[c2]).sum())
            cooc[f"{c1}|{c2}"] = both
    # MCAR t 检验：对每个缺失列，比较其他数值列在缺失/非缺失两组的均值
    mcar_tests = {}
    num_cols = df.select_dtypes(include="number").columns.tolist()
    for c in cols:
        if miss_rate[c] == 0:
            continue
        for other in num_cols:
            if other == c:
                continue
            g1 = df.loc[na_masks[c], other].dropna()
            g2 = df.loc[~na_masks[c], other].dropna()
            if len(g1) < 2 or len(g2) < 2:
                continue
            try:
                t, p = stats.ttest_ind(g1, g2, equal_var=False)
                mcar_tests[f"{c}|{other}"] = {"t": float(t), "p": float(p)}
            except Exception:
                continue
    # 缺失模式热力图
    miss_df = df.isna().astype(int)
    fig, ax = plt.subplots(figsize=(max(6, len(cols) * 0.5), 4))
    ax.imshow(miss_df.T, aspect="auto", cmap="Greys", interpolation="nearest")
    ax.set_yticks(range(len(cols)))
    ax.set_yticklabels(cols, fontsize=8)
    ax.set_xlabel("row")
    ax.set_title("missing pattern")
    fig.tight_layout()
    img_path = ws.root / "missing_pattern.png"
    fig.savefig(img_path)
    plt.close(fig)
    report = {"missing_rate": miss_rate, "co_occurrence": cooc, "mcar_tests": mcar_tests}
    ws.save_json(report, "missing_pattern.json")
    return {"success": True, **report, "image": str(img_path), "meta_file": str(ws.root / "missing_pattern.json")}


def table_join(ws, params):
    """多表关联：left_table + right_table → cleaned.csv"""
    left_name = params.get("left_table", "input.csv")
    right_name = params.get("right_table", "input_2.csv")
    left_on = params.get("left_on", "")
    right_on = params.get("right_on", "")
    how = params.get("how", "inner")
    left_path = ws.root / left_name
    right_path = ws.root / right_name
    if not left_path.exists() or not right_path.exists():
        return {"success": False, "error": f"table not found: {left_name} or {right_name}"}
    left_df = pd.read_csv(left_path)
    right_df = pd.read_csv(right_path)
    if left_on not in left_df.columns or right_on not in right_df.columns:
        return {"success": False, "error": "join key not found in one or both tables"}
    merged = pd.merge(left_df, right_df, left_on=left_on, right_on=right_on, how=how,
                      suffixes=("_left", "_right"))
    ws.save_csv(merged, "cleaned.csv")
    return {"success": True, "rows": int(len(merged)), "cols": int(len(merged.columns)),
            "columns": list(merged.columns)}


class DataProcessorServer(MCPServer):
    def __init__(self):
        super().__init__(name="data-processor", description="数据清洗与特征工程")
        self.register_tool(
            schema=ToolSchema(name="data_clean",
                description="缺失填充、类型转换、异常值处理与去重",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"},
                    "fill":{"type":"string","enum":["median","mean"]},
                    "strategy":{"type":"string","enum":["simple","knn","group"],"default":"simple"},
                    "outlier_method":{"type":"string","enum":["iqr","zscore","isoforest","mark"],"default":"iqr"},
                    "group_col":{"type":"string"}}}),
            handler=lambda **kw: data_clean(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="feature_engineer",
                description="分类编码、数值标准化、组合特征生成",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"},
                    "encode":{"type":"boolean"},
                    "scale":{"type":"boolean"},
                    "interaction":{"type":"boolean","default":False},
                    "binning":{"type":"boolean","default":False},
                    "datetime_feat":{"type":"boolean","default":False}}}),
            handler=lambda **kw: feature_engineer(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="feature_select",
                description="特征选择：VIF 剔除多重共线性 / 互信息 top half / RFE 包装法",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"},
                    "method":{"type":"string","enum":["vif","mutual_info","rfe"],"default":"vif"},
                    "target":{"type":"string"}}}),
            handler=lambda **kw: feature_select(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="missing_pattern",
                description="缺失模式分析：缺失率、共现矩阵、MCAR t 检验与热力图",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"}}}),
            handler=lambda **kw: missing_pattern(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="data_quality",
                description="数据质量体检：缺失/重复/唯一性/异常占比与体检评分",
                parameters={"type":"object","properties":{"ws":{"type":"string"}}}),
            handler=lambda **kw: data_quality(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="table_join",
                description="多表关联(inner/left/right/outer join)",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"},
                    "left_table":{"type":"string"}, "right_table":{"type":"string"},
                    "left_on":{"type":"string"}, "right_on":{"type":"string"},
                    "how":{"type":"string","enum":["inner","left","right","outer"]}
                }}),
            handler=lambda **kw: table_join(_resolve_ws(kw), kw))
