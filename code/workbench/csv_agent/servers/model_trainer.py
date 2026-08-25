from __future__ import annotations
from typing import Any, Dict
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge, Lasso
from sklearn.metrics import (accuracy_score, auc, f1_score, mean_absolute_error,
                             mean_squared_error, precision_score, recall_score,
                             r2_score, roc_auc_score, roc_curve)
from sklearn.model_selection import GridSearchCV, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

def _target_col(df, target):
    if target and target in df.columns:
        return target
    if target:
        for c in df.columns:
            if target in c:
                return c
    num = df.select_dtypes(include="number").columns
    return num[0] if len(num) else ""

def model_suggest(ws, params):
    path = ws.root / "cleaned.csv"
    if not path.exists():
        path = ws.root / "input.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target:
        return {"success": False, "error": "target column not found"}
    return {"success": True, "suggestion": {"target": target, "task": "regression",
            "models": ["LinearRegression", "RandomForest"],
            "hint": "优先 LinearRegression(可解释)+RandomForest(精度) 对比",
            "n_rows": int(len(df)), "n_features": int(len(df.columns)) - 1}}

def _build_regressors(models_param):
    """按逗号分隔的别名构建回归模型实例池；未知别名或缺失依赖自动跳过。"""
    pool = []
    for raw in str(models_param or "lr,rf").split(","):
        name = raw.strip().lower()
        if name == "lr":
            pool.append(("LinearRegression", LinearRegression()))
        elif name == "rf":
            pool.append(("RandomForest", RandomForestRegressor(n_estimators=50, random_state=42)))
        elif name == "ridge":
            pool.append(("Ridge", Ridge(alpha=1.0)))
        elif name == "lasso":
            pool.append(("Lasso", Lasso(alpha=0.1)))
        elif name == "xgboost":
            try:
                from xgboost import XGBRegressor
                pool.append(("XGBoost", XGBRegressor(n_estimators=50, random_state=42)))
            except ImportError:
                # 未安装 xgboost，自动跳过
                pass
    return pool

def model_train(ws, params):
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target:
        return {"success": False, "error": "target column not found"}
    X = df.select_dtypes(include="number").drop(columns=[target])
    # 排除目标列的衍生特征（如 price_scaled / price_bin / price_outlier），防止数据泄露
    leak_patterns = [f"{target}_scaled", f"{target}_bin", f"{target}_outlier",
                     f"{target}_x_", f"{target}_year", f"{target}_month", f"{target}_dayofweek"]
    leak_cols = [c for c in X.columns if any(c.startswith(p) or c == p for p in leak_patterns)]
    if leak_cols:
        X = X.drop(columns=leak_cols)
    if X.empty or len(df) < 10:
        return {"success": False, "error": "insufficient numeric features"}
    y_raw = df[target]
    y = pd.to_numeric(y_raw, errors="coerce")
    if y.isna().all():
        return {"success": False, "error": "target not numeric"}
    X = X.apply(pd.to_numeric, errors="coerce").fillna(X.median())
    y = y.fillna(y.median())
    x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

    # 解析新增参数（缺省时保持与原行为一致：lr,rf 且不做 CV / 调优）
    model_pool = _build_regressors(params.get("models", "lr,rf"))
    if not model_pool:
        return {"success": False, "error": "no valid model specified"}
    try:
        cv_folds = int(params.get("cv_folds", "0"))
    except (TypeError, ValueError):
        cv_folds = 0
    tune = str(params.get("tune", "false")).strip().lower() in ("true", "1", "yes")

    results = {}
    importances = []
    for name, model in model_pool:
        # tune=True 且为 rf/xgboost：使用 GridSearchCV 进行超参调优
        if tune and name in ("RandomForest", "XGBoost"):
            param_grid = {"n_estimators": [50, 100], "max_depth": [None, 10, 20]}
            gs = GridSearchCV(model, param_grid, cv=3)
            m = gs.fit(x_train, y_train).best_estimator_
        else:
            m = model.fit(x_train, y_train)
        pred = m.predict(x_test)
        result = {
            "rmse": round(float(mean_squared_error(y_test, pred) ** 0.5), 4),
            "mae": round(float(mean_absolute_error(y_test, pred)), 4),
            "r2": round(float(r2_score(y_test, pred)), 4),
        }
        # cv_folds>=2 时附加交叉验证 R2 均值/标准差
        if cv_folds >= 2:
            cv_scores = cross_val_score(model, X, y, cv=cv_folds)
            result["cv_r2_mean"] = round(float(cv_scores.mean()), 4)
            result["cv_r2_std"] = round(float(cv_scores.std()), 4)
        if hasattr(m, "feature_importances_"):
            imp = dict(zip(X.columns, (round(float(v), 4) for v in m.feature_importances_)))
            importances = sorted(imp.items(), key=lambda kv: kv[1], reverse=True)
        results[name] = result
    best = min(results, key=lambda k: results[k]["rmse"])
    ws.save_json({"results": results, "best": best, "importance": importances}, "model_metrics.json")
    # metrics 默认回退到 RandomForest（兼容旧调用），缺失时取 best
    return {"success": True, "target": target, "metrics": results.get("RandomForest", results[best]),
            "best_model": best, "feature_importance": dict(importances), "all_metrics": results}

def model_classify(ws, params):
    """分类建模：目标为类别列，输出准确率/精确率/召回率/F1 与混淆矩阵图。"""
    path = ws.root / "cleaned.csv"
    if not path.exists():
        path = ws.root / "input.csv"
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target or len(df[target].dropna().unique()) < 2:
        return {"success": False, "error": "target must be a categorical column with >=2 classes"}
    X = df.select_dtypes(include="number").drop(columns=[target], errors="ignore")
    # 排除目标列的衍生特征，防止数据泄露
    leak_patterns = [f"{target}_scaled", f"{target}_bin", f"{target}_outlier",
                     f"{target}_x_", f"{target}_year", f"{target}_month", f"{target}_dayofweek"]
    leak_cols = [c for c in X.columns if any(c.startswith(p) or c == p for p in leak_patterns)]
    if leak_cols:
        X = X.drop(columns=leak_cols)
    # 去除含 NaN 的数值列，保证可训练
    X = X.dropna(axis=1)
    if X.empty or len(df) < 20:
        return {"success": False, "error": "insufficient numeric features"}
    y_raw = df[target]
    y = y_raw.astype("category").cat.codes
    y = y[y != -1]  # 过滤 NaN 类
    X = X.loc[y.index]
    if y.nunique() < 2:
        return {"success": False, "error": "single class after cleaning"}
    x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
    models = [("LogisticRegression", LogisticRegression(max_iter=1000)),
              ("RandomForest", RandomForestClassifier(n_estimators=50, random_state=42))]
    results = {}
    is_binary = y.nunique() == 2
    for name, model in models:
        m = model.fit(x_train, y_train)
        pred = m.predict(x_test)
        result = {"accuracy": round(float(accuracy_score(y_test, pred)), 4),
                  "precision": round(float(precision_score(y_test, pred, average="weighted", zero_division=0)), 4),
                  "recall": round(float(recall_score(y_test, pred, average="weighted", zero_division=0)), 4),
                  "f1": round(float(f1_score(y_test, pred, average="weighted", zero_division=0)), 4)}
        # 二分类时基于 predict_proba 计算 ROC-AUC
        if is_binary and hasattr(m, "predict_proba"):
            proba = m.predict_proba(x_test)
            if proba.shape[1] == 2:
                result["roc_auc"] = round(float(roc_auc_score(y_test, proba[:, 1])), 4)
        results[name] = result
    best = max(results, key=lambda k: results[k]["accuracy"])
    # 混淆矩阵图（用最优模型在测试集上绘制）
    from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
    best_model = dict(models)[best].fit(x_train, y_train)
    pred = best_model.predict(x_test)
    labels = sorted(set(y_test) | set(pred))
    cm = confusion_matrix(y_test, pred, labels=labels)
    import os, tempfile, matplotlib
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from code.workbench.csv_agent.servers.visualizer import _setup_cjk_font
    _setup_cjk_font(); plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(6, 5))
    disp = ConfusionMatrixDisplay(cm, display_labels=labels)
    disp.plot(ax=ax, cmap="Blues", colorbar=False)
    ax.set_title(f"混淆矩阵 ({best})")
    fig.tight_layout()
    img = ws.charts_dir / "confusion.png"
    fig.savefig(img, dpi=90); plt.close(fig)
    # 二分类时绘制 ROC 曲线并保存 roc_curve.png
    roc_chart = None
    if is_binary and hasattr(best_model, "predict_proba"):
        proba = best_model.predict_proba(x_test)
        if proba.shape[1] == 2:
            fpr, tpr, _ = roc_curve(y_test, proba[:, 1])
            roc_auc = auc(fpr, tpr)
            fig2, ax2 = plt.subplots(figsize=(6, 5))
            ax2.plot(fpr, tpr, label=f"{best} (AUC={roc_auc:.4f})")
            ax2.plot([0, 1], [0, 1], "--", color="gray")
            ax2.set_xlabel("False Positive Rate")
            ax2.set_ylabel("True Positive Rate")
            ax2.set_title(f"ROC 曲线 ({best})")
            ax2.legend(loc="lower right")
            fig2.tight_layout()
            roc_img = ws.charts_dir / "roc_curve.png"
            fig2.savefig(roc_img, dpi=90); plt.close(fig2)
            roc_chart = roc_img.name
    ws.save_json({"results": results, "best": best}, "model_metrics.json")
    return {"success": True, "target": target, "metrics": results[best],
            "best_model": best, "classes": int(y.nunique()), "chart": img.name,
            "all_metrics": results, "roc_chart": roc_chart}


class ModelTrainerServer(MCPServer):
    def __init__(self):
        super().__init__(name="model-trainer", description="模型建议与训练")
        self.register_tool(
            schema=ToolSchema(name="model_suggest",
                description="根据数据特征推荐模型",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"goal":{"type":"string"},"target":{"type":"string"}}}),
            handler=lambda **kw: model_suggest(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="model_train",
                description="训练回归模型并返回评估指标与特征重要性。支持 lr/rf/ridge/lasso/xgboost，可选交叉验证与超参调优",
                parameters={"type":"object","properties":{
                    "ws":{"type":"string"},
                    "target":{"type":"string"},
                    "models":{"type":"string","description":"逗号分隔的模型别名列表，可选 lr,rf,ridge,lasso,xgboost，默认 lr,rf"},
                    "cv_folds":{"type":"string","description":"交叉验证折数，0 表示不做交叉验证，默认 0"},
                    "tune":{"type":"string","description":"是否对 rf/xgboost 启用 GridSearchCV 超参调优，默认 false"}
                }}),
            handler=lambda **kw: model_train(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="model_classify",
                description="训练分类模型并返回准确率/精确率/召回率/F1 与混淆矩阵",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"target":{"type":"string"}}}),
            handler=lambda **kw: model_classify(_resolve_ws(kw), kw))