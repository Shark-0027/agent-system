"""
状态管理模块。

提供 StateManager 类，用于管理 Agent 运行时的完整状态，
包括消息历史、工具调用记录、观察结果和元数据。
支持状态快照、序列化和恢复。
"""

import copy
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_runtime.state")


class StateManager:
    """Agent 运行时状态管理器。

    管理 Agent 执行过程中的所有状态信息，包括：
    - 消息历史（对话记录）
    - 当前执行步数
    - 工具调用记录
    - 观察结果
    - 用户自定义元数据

    Attributes:
        messages: 对话消息列表。
        current_step: 当前执行步数。
        tool_calls: 历史工具调用记录列表。
        observations: 历史观察结果列表。
        metadata: 用户自定义元数据。
        created_at: 状态创建时间。
        updated_at: 状态最后更新时间。
    """

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.current_step: int = 0
        self.tool_calls: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}
        self.created_at: str = datetime.now().isoformat()
        self.updated_at: str = self.created_at

    def _touch(self) -> None:
        """更新最后修改时间。"""
        self.updated_at = datetime.now().isoformat()

    def add_message(self, role: str, content: Optional[str] = None, **kwargs: Any) -> None:
        """添加一条对话消息。

        Args:
            role: 消息角色（'system', 'user', 'assistant', 'tool'）。
            content: 消息内容。
            **kwargs: 额外的消息字段（如 tool_calls, tool_call_id, name 等）。
        """
        message: Dict[str, Any] = {"role": role}
        if content is not None:
            message["content"] = content
        message.update(kwargs)
        self.messages.append(message)
        self._touch()
        logger.debug("Added message: role=%s, content_len=%d", role, len(content or ""))

    def add_tool_call(self, tool_call: Dict[str, Any]) -> None:
        """记录一次工具调用。

        Args:
            tool_call: 工具调用信息字典，包含 name, arguments, id 等。
        """
        record = {
            "step": self.current_step,
            "timestamp": datetime.now().isoformat(),
            **tool_call,
        }
        self.tool_calls.append(record)
        self._touch()
        logger.debug("Added tool call: %s", tool_call.get("name", "unknown"))

    def add_observation(self, observation: Dict[str, Any]) -> None:
        """记录一次观察结果。

        Args:
            observation: 观察结果字典，包含 tool_name, result, error 等。
        """
        record = {
            "step": self.current_step,
            "timestamp": datetime.now().isoformat(),
            **observation,
        }
        self.observations.append(record)
        self._touch()
        logger.debug("Added observation at step %d", self.current_step)

    def increment_step(self) -> int:
        """递增当前步数并返回新值。

        Returns:
            递增后的步数。
        """
        self.current_step += 1
        self._touch()
        return self.current_step

    def get_messages(self) -> List[Dict[str, Any]]:
        """获取对话消息列表。

        Returns:
            消息列表的副本。
        """
        return list(self.messages)

    def get_history(self) -> List[Dict[str, Any]]:
        """获取完整的对话历史（同 get_messages）。

        Returns:
            消息列表的副本。
        """
        return self.get_messages()

    def get_last_n_messages(self, n: int) -> List[Dict[str, Any]]:
        """获取最近 N 条消息。

        Args:
            n: 要获取的消息数量。

        Returns:
            最近 N 条消息列表。
        """
        return self.messages[-n:] if n > 0 else []

    def get_latest_tool_calls(self, n: int = 5) -> List[Dict[str, Any]]:
        """获取最近 N 次工具调用记录。

        Args:
            n: 要获取的记录数量。

        Returns:
            最近 N 次工具调用记录。
        """
        return self.tool_calls[-n:] if n > 0 else []

    def snapshot(self) -> Dict[str, Any]:
        """创建当前状态的快照。

        Returns:
            深拷贝的完整状态字典。
        """
        return self.to_dict()

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """从快照恢复状态。

        Args:
            snapshot: 之前通过 snapshot() 或 to_dict() 获取的状态字典。
        """
        self.from_dict(snapshot)
        logger.info("State restored from snapshot")

    def to_dict(self) -> Dict[str, Any]:
        """将状态序列化为字典。

        Returns:
            包含所有状态字段的字典。
        """
        return {
            "messages": copy.deepcopy(self.messages),
            "current_step": self.current_step,
            "tool_calls": copy.deepcopy(self.tool_calls),
            "observations": copy.deepcopy(self.observations),
            "metadata": copy.deepcopy(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """从字典恢复状态。

        Args:
            data: 包含状态数据的字典。
        """
        self.messages = copy.deepcopy(data.get("messages", []))
        self.current_step = data.get("current_step", 0)
        self.tool_calls = copy.deepcopy(data.get("tool_calls", []))
        self.observations = copy.deepcopy(data.get("observations", []))
        self.metadata = copy.deepcopy(data.get("metadata", {}))
        self.created_at = data.get("created_at", datetime.now().isoformat())
        self.updated_at = data.get("updated_at", datetime.now().isoformat())
        self._touch()

    def to_json(self) -> str:
        """将状态序列化为 JSON 字符串。

        Returns:
            JSON 格式的状态字符串。
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def from_json(self, json_str: str) -> None:
        """从 JSON 字符串恢复状态。

        Args:
            json_str: JSON 格式的状态字符串。
        """
        data = json.loads(json_str)
        self.from_dict(data)

    def clear(self) -> None:
        """清空所有状态数据。"""
        self.messages.clear()
        self.current_step = 0
        self.tool_calls.clear()
        self.observations.clear()
        self.metadata.clear()
        self.created_at = datetime.now().isoformat()
        self._touch()
        logger.info("State cleared")

    def __repr__(self) -> str:
        return (
            f"StateManager(step={self.current_step}, "
            f"messages={len(self.messages)}, "
            f"tool_calls={len(self.tool_calls)}, "
            f"observations={len(self.observations)})"
        )