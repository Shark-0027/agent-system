from __future__ import annotations
from typing import Any, Dict
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (accuracy_score, f1_score, mean_absolute_error,
                             mean_squared_error, precision_score, recall_score,
                             r2_score)
from sklearn.model_selection import train_test_split
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

def model_train(ws, params):
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target:
        return {"success": False, "error": "target column not found"}
    X = df.select_dtypes(include="number").drop(columns=[target])
    if X.empty or len(df) < 10:
        return {"success": False, "error": "insufficient numeric features"}
    y_raw = df[target]
    y = pd.to_numeric(y_raw, errors="coerce")
    if y.isna().all():
        return {"success": False, "error": "target not numeric"}
    X = X.apply(pd.to_numeric, errors="coerce").fillna(X.median())
    y = y.fillna(y.median())
    x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
    results = {}
    importances = []
    for name, model in [("LinearRegression", LinearRegression()), ("RandomForest", RandomForestRegressor(n_estimators=50, random_state=42))]:
        m = model.fit(x_train, y_train)
        pred = m.predict(x_test)
        results[name] = {"rmse": round(float(mean_squared_error(y_test, pred) ** 0.5), 4),
                         "mae": round(float(mean_absolute_error(y_test, pred)), 4),
                         "r2": round(float(r2_score(y_test, pred)), 4)}
        if hasattr(m, "feature_importances_"):
            imp = dict(zip(X.columns, (round(float(v), 4) for v in m.feature_importances_)))
            importances = sorted(imp.items(), key=lambda kv: kv[1], reverse=True)
    best = min(results, key=lambda k: results[k]["rmse"])
    ws.save_json({"results": results, "best": best, "importance": importances}, "model_metrics.json")
    return {"success": True, "target": target, "metrics": results["RandomForest"],
            "best_model": best, "feature_importance": dict(importances)}

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
    for name, model in models:
        m = model.fit(x_train, y_train)
        pred = m.predict(x_test)
        results[name] = {"accuracy": round(float(accuracy_score(y_test, pred)), 4),
                         "precision": round(float(precision_score(y_test, pred, average="weighted", zero_division=0)), 4),
                         "recall": round(float(recall_score(y_test, pred, average="weighted", zero_division=0)), 4),
                         "f1": round(float(f1_score(y_test, pred, average="weighted", zero_division=0)), 4)}
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
    ws.save_json({"results": results, "best": best}, "model_metrics.json")
    return {"success": True, "target": target, "metrics": results[best],
            "best_model": best, "classes": int(y.nunique()), "chart": img.name}


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
                description="训练回归模型并返回评估指标与特征重要性",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"target":{"type":"string"}}}),
            handler=lambda **kw: model_train(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="model_classify",
                description="训练分类模型并返回准确率/精确率/召回率/F1 与混淆矩阵",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"target":{"type":"string"}}}),
            handler=lambda **kw: model_classify(_resolve_ws(kw), kw))