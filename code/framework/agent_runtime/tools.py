"""
工具定义与注册表模块。

提供 Tool 数据类用于定义可调用的工具函数，
以及 ToolRegistry 类用于管理工具的生命周期。
"""

import json
import logging
import jsonschema
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .exceptions import ToolNotFoundException, InvalidToolParameterException

logger = logging.getLogger("agent_runtime.tools")


@dataclass
class Tool:
    """工具定义。

    表示一个可供 Agent 调用的工具函数，包含名称、描述、
    参数 Schema 和执行函数。

    Attributes:
        name: 工具名称，用于唯一标识。
        description: 工具功能描述，帮助模型理解何时调用。
        parameters: 参数 JSON Schema 定义。
        function: 可调用的执行函数。
        required: 必填参数列表。
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    function: Callable[..., Any]

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式。

        Returns:
            符合 OpenAI function calling 规范的工具定义字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, **kwargs: Any) -> Any:
        """校验参数并执行工具函数。

        Args:
            **kwargs: 传递给工具函数的参数。

        Returns:
            工具函数的返回值。

        Raises:
            InvalidToolParameterException: 当参数不符合 Schema 时抛出。
        """
        try:
            jsonschema.validate(instance=kwargs, schema=self.parameters)
        except jsonschema.ValidationError as e:
            raise InvalidToolParameterException(
                tool_name=self.name,
                invalid_params={"error": str(e), "provided": kwargs},
            ) from e

        try:
            logger.debug("Executing tool '%s' with args: %s", self.name, kwargs)
            result = self.function(**kwargs)
            logger.debug("Tool '%s' returned: %s", self.name, str(result)[:200])
            return result
        except Exception as e:
            logger.error("Tool '%s' execution failed: %s", self.name, e)
            raise


class ToolRegistry:
    """工具注册表。

    管理所有已注册的工具，支持添加、移除、搜索和格式转换。

    Attributes:
        _tools: 工具名称到 Tool 对象的映射字典。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具。

        Args:
            tool: 要注册的 Tool 对象。

        Raises:
            ValueError: 当工具名称已存在时抛出。
        """
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                f"Use unregister() first to replace it."
            )
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> None:
        """注销一个工具。

        Args:
            name: 要注销的工具名称。

        Raises:
            ToolNotFoundException: 当工具不存在时抛出。
        """
        if name not in self._tools:
            raise ToolNotFoundException(name)
        del self._tools[name]
        logger.info("Unregistered tool: %s", name)

    def get(self, name: str) -> Tool:
        """获取指定名称的工具。

        Args:
            name: 工具名称。

        Returns:
            对应的 Tool 对象。

        Raises:
            ToolNotFoundException: 当工具不存在时抛出。
        """
        if name not in self._tools:
            raise ToolNotFoundException(name)
        return self._tools[name]

    def list_all(self) -> List[Tool]:
        """获取所有已注册工具的列表。

        Returns:
            Tool 对象列表。
        """
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        """获取所有已注册工具的名称列表。

        Returns:
            工具名称列表。
        """
        return list(self._tools.keys())

    def get_tools_openai_format(self) -> List[Dict[str, Any]]:
        """获取所有工具的 OpenAI function calling 格式列表。

        Returns:
            工具定义的 OpenAI 格式列表。
        """
        return [tool.to_openai_format() for tool in self._tools.values()]

    def search_by_description(self, query: str) -> List[Tool]:
        """根据描述关键词搜索工具。

        对工具名称和描述进行不区分大小写的关键词匹配。

        Args:
            query: 搜索关键词。

        Returns:
            匹配的 Tool 对象列表。
        """
        query_lower = query.lower()
        results: List[Tool] = []
        for tool in self._tools.values():
            if query_lower in tool.name.lower() or query_lower in tool.description.lower():
                results.append(tool)
        return results

    def execute(self, name: str, **kwargs: Any) -> Any:
        """根据名称执行工具。

        Args:
            name: 工具名称。
            **kwargs: 传递给工具的参数。

        Returns:
            工具执行结果。

        Raises:
            ToolNotFoundException: 当工具不存在时抛出。
        """
        tool = self.get(name)
        return tool.execute(**kwargs)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={list(self._tools.keys())})"