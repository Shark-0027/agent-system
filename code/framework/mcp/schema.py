"""
MCP Tool Schema 定义

ToolSchema 定义了 MCP 工具的参数 Schema，支持 JSON Schema 格式，
提供参数校验、序列化等核心功能。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# 类型常量
# ---------------------------------------------------------------------------

SUPPORTED_TYPES = frozenset({
    "string", "number", "integer", "boolean", "array", "object",
})

JSONSchemaType = Dict[str, Any]


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class SchemaValidationError(Exception):
    """Schema 校验异常。"""

    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(message)
        self.path = path


class ParameterValidationError(SchemaValidationError):
    """参数校验异常 -- 携带参数路径。"""


# ---------------------------------------------------------------------------
# ToolSchema
# ---------------------------------------------------------------------------

@dataclass
class ToolSchema:
    """MCP 工具 Schema 定义。

    描述一个 MCP 工具的元数据，包括名称、描述、参数 Schema 和版本号。
    参数 Schema 遵循 JSON Schema 规范。
    """

    name: str
    """工具名称（唯一标识）。"""

    description: str
    """工具功能描述，用于 LLM 工具选择。"""

    parameters: JSONSchemaType = field(default_factory=dict)
    """JSON Schema 格式的参数定义。"""

    version: str = "1.0.0"
    """工具版本号，遵循语义化版本规范。"""

    # -- 内部缓存 ------------------------------------------------------------

    __required_set: Optional[frozenset] = field(default=None, repr=False, init=False)
    __defaults: Optional[Dict[str, Any]] = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        """初始化后执行：校验自身 Schema 合法性并缓存必要数据。"""
        # 校验 version 格式
        if not isinstance(self.version, str):
            raise SchemaValidationError(
                f"version must be a string, got {type(self.version).__name__}"
            )
        # 校验 parameters 顶层结构
        if not isinstance(self.parameters, dict):
            raise SchemaValidationError(
                f"parameters must be a dict, got {type(self.parameters).__name__}"
            )
        # 初始化缓存
        self._cache()

    def _cache(self) -> None:
        """缓存 required 集合和默认值映射。"""
        props = self.parameters.get("properties", {})
        required_list: List[str] = list(self.parameters.get("required", []))
        self.__required_set = frozenset(required_list)
        defaults: Dict[str, Any] = {}
        for key, prop in props.items():
            if isinstance(prop, dict) and "default" in prop:
                defaults[key] = prop["default"]
        self.__defaults = defaults

    @property
    def _required_set(self) -> frozenset:
        if self.__required_set is None:
            self._cache()
        return self.__required_set  # type: ignore[return-value]

    @property
    def _defaults(self) -> Dict[str, Any]:
        if self.__defaults is None:
            self._cache()
        return self.__defaults  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 参数校验
    # ------------------------------------------------------------------

    def validate_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """校验参数字典是否符合当前 Schema。

        步骤：
        1. 填充默认值
        2. 检查必填字段
        3. 逐字段类型校验 + enum 约束校验
        4. 返回完整参数（含已填充的默认值）

        Raises:
            ParameterValidationError: 参数不合法时抛出。
        """
        props = self.parameters.get("properties", {})
        # 1. 填充默认值
        validated: Dict[str, Any] = dict(kwargs)
        for key, default_val in self._defaults.items():
            if key not in validated:
                validated[key] = copy.deepcopy(default_val)

        # 2. 检查必填字段
        for key in self._required_set:
            if key not in validated:
                raise ParameterValidationError(
                    f"Missing required parameter: '{key}'", path=key
                )

        # 3. 逐字段校验
        for key, value in validated.items():
            if key not in props:
                continue  # 允许额外参数（宽松模式）
            prop_schema = props[key]
            if not isinstance(prop_schema, dict):
                continue
            self._validate_single_param(key, value, prop_schema)

        return validated

    def _validate_single_param(
        self, key: str, value: Any, prop_schema: Dict[str, Any]
    ) -> None:
        """校验单个参数。"""
        type_ = prop_schema.get("type")

        # 类型校验
        if type_ is not None:
            if type_ not in SUPPORTED_TYPES:
                raise ParameterValidationError(
                    f"Unsupported type '{type_}' for parameter '{key}'", path=key
                )
            if not self._check_type(value, type_):
                raise ParameterValidationError(
                    f"Parameter '{key}' expected type '{type_}', got '{type(value).__name__}'",
                    path=key,
                )

        # enum 约束
        enum_values = prop_schema.get("enum")
        if enum_values is not None:
            if isinstance(enum_values, list) and value not in enum_values:
                raise ParameterValidationError(
                    f"Parameter '{key}' value '{value}' not in enum {enum_values}",
                    path=key,
                )

        # 嵌套 array 校验
        if type_ == "array" and isinstance(value, list):
            items_schema = prop_schema.get("items")
            if isinstance(items_schema, dict):
                for i, item in enumerate(value):
                    self._validate_single_param(f"{key}[{i}]", item, items_schema)

        # 嵌套 object 校验
        if type_ == "object" and isinstance(value, dict):
            nested_props = prop_schema.get("properties", {})
            nested_required = prop_schema.get("required", [])
            for nk, nv in value.items():
                if nk in nested_props and isinstance(nested_props[nk], dict):
                    self._validate_single_param(
                        f"{key}.{nk}", nv, nested_props[nk]
                    )
            for nk in nested_required:
                if nk not in value:
                    raise ParameterValidationError(
                        f"Missing required nested parameter: '{key}.{nk}'", path=key
                    )

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """检查值是否匹配期望类型。"""
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return False

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """将 ToolSchema 序列化为字典。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(self.parameters),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolSchema":
        """从字典反序列化创建 ToolSchema。"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            version=data.get("version", "1.0.0"),
        )

    def __repr__(self) -> str:
        return (
            f"ToolSchema(name={self.name!r}, version={self.version!r}, "
            f"params_count={len(self.parameters.get('properties', {}))})"
        )


# ---------------------------------------------------------------------------
# 便捷工厂函数
# ---------------------------------------------------------------------------

def make_tool_schema(
    name: str,
    description: str,
    parameters: Optional[JSONSchemaType] = None,
    version: str = "1.0.0",
) -> ToolSchema:
    """快速创建 ToolSchema 的工厂函数。"""
    return ToolSchema(
        name=name,
        description=description,
        parameters=parameters or {},
        version=version,
    )