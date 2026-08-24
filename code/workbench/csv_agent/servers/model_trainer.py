from __future__ import annotations
from typing import Any, Dict
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
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