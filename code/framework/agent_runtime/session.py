"""
会话管理模块。

提供 SessionManager 类，用于管理多个 Agent 会话的生命周期，
保证各会话之间严格的状态隔离。
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .state import StateManager
from .exceptions import SessionNotFoundException

logger = logging.getLogger("agent_runtime.session")


class SessionManager:
    """会话管理器。

    管理多个 Agent 会话的创建、获取、删除和列表，
    每个会话拥有独立的 StateManager 实例。

    Attributes:
        _sessions: 会话 ID 到 StateManager 的映射字典。
        _session_metadata: 会话元数据字典。
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, StateManager] = {}
        self._session_metadata: Dict[str, Dict] = {}

    def create_session(self, session_id: Optional[str] = None) -> str:
        """创建一个新会话。

        Args:
            session_id: 可选的会话 ID。如果不提供则自动生成 UUID。

        Returns:
            新创建的会话 ID。

        Raises:
            ValueError: 当指定的 session_id 已存在时抛出。
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        elif session_id in self._sessions:
            raise ValueError(f"Session '{session_id}' already exists. Use a different ID.")

        self._sessions[session_id] = StateManager()
        self._session_metadata[session_id] = {
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "message_count": 0,
        }
        logger.info("Created session: %s", session_id)
        return session_id

    def get_session(self, session_id: str) -> StateManager:
        """获取指定会话的状态管理器。

        Args:
            session_id: 会话 ID。

        Returns:
            对应的 StateManager 实例。

        Raises:
            SessionNotFoundException: 当会话不存在时抛出。
        """
        if session_id not in self._sessions:
            raise SessionNotFoundException(session_id)
        state = self._sessions[session_id]
        self._session_metadata[session_id]["last_active"] = datetime.now().isoformat()
        self._session_metadata[session_id]["message_count"] = len(state.messages)
        return state

    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        """获取现有会话，如果不存在则创建。

        Args:
            session_id: 会话 ID。如果为 None 则始终创建新会话。

        Returns:
            会话 ID。
        """
        if session_id and session_id in self._sessions:
            logger.debug("Using existing session: %s", session_id)
            return session_id
        return self.create_session(session_id)

    def delete_session(self, session_id: str) -> None:
        """删除一个会话。

        Args:
            session_id: 要删除的会话 ID。

        Raises:
            SessionNotFoundException: 当会话不存在时抛出。
        """
        if session_id not in self._sessions:
            raise SessionNotFoundException(session_id)
        del self._sessions[session_id]
        self._session_metadata.pop(session_id, None)
        logger.info("Deleted session: %s", session_id)

    def list_sessions(self) -> List[str]:
        """获取所有活跃会话的 ID 列表。

        Returns:
            会话 ID 列表，按创建时间排序。
        """
        return sorted(
            self._sessions.keys(),
            key=lambda sid: self._session_metadata.get(sid, {}).get("created_at", ""),
        )

    def session_exists(self, session_id: str) -> bool:
        """检查会话是否存在。

        Args:
            session_id: 会话 ID。

        Returns:
            会话是否存在。
        """
        return session_id in self._sessions

    def get_session_info(self, session_id: str) -> Dict:
        """获取会话信息。

        Args:
            session_id: 会话 ID。

        Returns:
            包含会话元数据和状态摘要的字典。

        Raises:
            SessionNotFoundException: 当会话不存在时抛出。
        """
        if session_id not in self._sessions:
            raise SessionNotFoundException(session_id)
        state = self._sessions[session_id]
        metadata = self._session_metadata.get(session_id, {})
        return {
            "session_id": session_id,
            "metadata": dict(metadata),
            "state_summary": {
                "current_step": state.current_step,
                "message_count": len(state.messages),
                "tool_call_count": len(state.tool_calls),
                "observation_count": len(state.observations),
            },
        }

    def clear_all(self) -> None:
        """清空所有会话。"""
        count = len(self._sessions)
        self._sessions.clear()
        self._session_metadata.clear()
        logger.info("Cleared all %d sessions", count)

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    def __repr__(self) -> str:
        return f"SessionManager(sessions={len(self._sessions)})"