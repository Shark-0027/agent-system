"""
Trace 日志记录模块。

提供 TraceLogger 类，用于记录 Agent 运行过程中的完整调用链路，
支持结构化的事件记录、持久化存储和回放展示。
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_runtime.trace")


class TraceLogger:
    """Trace 日志记录器。

    记录 Agent 执行过程中的所有关键事件，包括：
    - LLM 调用
    - 工具调用
    - 观察结果
    - 错误
    - 终止条件

    支持同时输出到控制台和文件，并提供 JSON 格式的持久化保存。

    Attributes:
        trace: 事件记录列表。
        session_id: 关联的会话 ID。
        verbose: 是否在控制台详细输出。
        log_file: 可选的日志文件路径。
    """

    VALID_EVENT_TYPES = frozenset({
        "llm_call",
        "tool_call",
        "tool_result",
        "observation",
        "error",
        "termination",
    })

    def __init__(
        self,
        session_id: Optional[str] = None,
        verbose: bool = True,
        log_file: Optional[str] = None,
    ) -> None:
        """初始化 Trace 记录器。

        Args:
            session_id: 关联的会话 ID。
            verbose: 是否在控制台输出详细日志。
            log_file: 日志文件路径。如果提供，同时将 trace 写入文件。
        """
        self.trace: List[Dict[str, Any]] = []
        self.session_id = session_id or "unknown"
        self.verbose = verbose
        self.log_file = log_file

        if self.log_file:
            os.makedirs(os.path.dirname(self.log_file) or ".", exist_ok=True)

        logger.info(
            "TraceLogger initialized: session=%s, verbose=%s, log_file=%s",
            self.session_id,
            self.verbose,
            self.log_file,
        )

    def log_step(
        self,
        step_num: int,
        event_type: str,
        data: Dict[str, Any],
        duration_ms: Optional[float] = None,
    ) -> None:
        """记录一个 trace 事件。

        Args:
            step_num: 当前步数。
            event_type: 事件类型，必须是 VALID_EVENT_TYPES 之一。
            data: 事件相关的数据字典。
            duration_ms: 事件耗时（毫秒），可选。

        Raises:
            ValueError: 当 event_type 不在有效类型列表中时抛出。
        """
        if event_type not in self.VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type '{event_type}'. "
                f"Must be one of: {sorted(self.VALID_EVENT_TYPES)}"
            )

        event: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "step": step_num,
            "event_type": event_type,
            "data": data,
        }
        if duration_ms is not None:
            event["duration_ms"] = duration_ms

        self.trace.append(event)

        if self.verbose:
            self._print_event(event)

        if self.log_file:
            self._write_to_file(event)

        logger.debug("Trace: step=%d, event=%s", step_num, event_type)

    def _print_event(self, event: Dict[str, Any]) -> None:
        """在控制台输出事件信息。

        Args:
            event: 事件字典。
        """
        step = event["step"]
        event_type = event["event_type"]
        data = event["data"]
        duration = event.get("duration_ms")

        indent = "  " * min(step, 10)

        if event_type == "llm_call":
            messages_count = data.get("messages_count", 0)
            tools_count = data.get("tools_count", 0)
            has_tool_calls = data.get("has_tool_calls", False)
            content_preview = str(data.get("content_preview", ""))[:80]
            print(
                f"{indent}[Step {step}] LLM Call: "
                f"msgs={messages_count}, tools={tools_count}"
            )
            if has_tool_calls:
                tool_names = data.get("tool_names", [])
                print(f"{indent}  -> Tool calls: {tool_names}")
            if content_preview:
                print(f"{indent}  -> Content: {content_preview}")

        elif event_type == "tool_call":
            tool_name = data.get("tool_name", "unknown")
            print(f"{indent}[Step {step}] Tool Call: {tool_name}")

        elif event_type == "tool_result":
            tool_name = data.get("tool_name", "unknown")
            success = data.get("success", False)
            result_preview = str(data.get("result", ""))[:100]
            status = "OK" if success else "FAILED"
            print(f"{indent}[Step {step}] Tool Result [{status}]: {tool_name}")
            if result_preview:
                print(f"{indent}  -> {result_preview}")

        elif event_type == "observation":
            obs_type = data.get("observation_type", "general")
            print(f"{indent}[Step {step}] Observation: {obs_type}")

        elif event_type == "error":
            error_type = data.get("error_type", "unknown")
            error_msg = str(data.get("error_message", ""))[:100]
            print(f"{indent}[Step {step}] Error [{error_type}]: {error_msg}")

        elif event_type == "termination":
            reason = data.get("reason", "unknown")
            print(f"\n{'='*60}")
            print(f"Agent terminated: {reason}")
            print(f"{'='*60}")

        if duration is not None:
            print(f"{indent}  (took {duration:.0f}ms)")

    def _write_to_file(self, event: Dict[str, Any]) -> None:
        """将事件追加写入日志文件。

        Args:
            event: 事件字典。
        """
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:  # type: ignore
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to write trace to file %s: %s", self.log_file, e)

    def get_trace(self) -> List[Dict[str, Any]]:
        """获取完整的 trace 记录。

        Returns:
            事件记录列表的副本。
        """
        return list(self.trace)

    def get_trace_summary(self) -> Dict[str, Any]:
        """获取 trace 摘要信息。

        Returns:
            包含各类事件计数的摘要字典。
        """
        event_counts: Dict[str, int] = {}
        total_duration_ms: float = 0.0
        errors: List[Dict[str, Any]] = []

        for event in self.trace:
            event_type = event["event_type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

            if event.get("duration_ms"):
                total_duration_ms += event["duration_ms"]

            if event_type == "error":
                errors.append({
                    "step": event["step"],
                    "error_type": event["data"].get("error_type", "unknown"),
                    "error_message": event["data"].get("error_message", ""),
                })

        steps = [e["step"] for e in self.trace]
        return {
            "session_id": self.session_id,
            "total_events": len(self.trace),
            "event_counts": event_counts,
            "total_duration_ms": total_duration_ms,
            "total_steps": max(steps) if steps else 0,
            "errors": errors,
            "start_time": self.trace[0]["timestamp"] if self.trace else None,
            "end_time": self.trace[-1]["timestamp"] if self.trace else None,
        }

    def save_trace(self, filepath: str) -> None:
        """将完整 trace 保存为 JSON 文件。

        Args:
            filepath: 保存路径。
        """
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        output = {
            "session_id": self.session_id,
            "saved_at": datetime.now().isoformat(),
            "summary": self.get_trace_summary(),
            "trace": self.trace,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info("Trace saved to: %s (%d events)", filepath, len(self.trace))

    def replay(self) -> str:
        """生成 trace 回放展示文本。

        Returns:
            格式化的 trace 回放文本。
        """
        lines: List[str] = []
        lines.append(f"{'='*70}")
        lines.append(f"  Agent Trace Replay - Session: {self.session_id}")
        lines.append(f"{'='*70}")

        for event in self.trace:
            step = event["step"]
            event_type = event["event_type"]
            data = event["data"]
            duration = event.get("duration_ms")

            lines.append(f"\n--- Step {step} | {event_type} ---")

            if event_type == "llm_call":
                lines.append(f"  Messages: {data.get('messages_count', 0)}")
                lines.append(f"  Tools available: {data.get('tools_count', 0)}")
                if data.get("has_tool_calls"):
                    lines.append(f"  Tool calls: {data.get('tool_names', [])}")
                if data.get("content_preview"):
                    lines.append(f"  Content: {data['content_preview']}")

            elif event_type == "tool_call":
                lines.append(f"  Tool: {data.get('tool_name', 'unknown')}")
                args = data.get("arguments", {})
                lines.append(f"  Arguments: {json.dumps(args, ensure_ascii=False)}")

            elif event_type == "tool_result":
                lines.append(f"  Tool: {data.get('tool_name', 'unknown')}")
                lines.append(f"  Success: {data.get('success', False)}")
                result = data.get("result", "")
                lines.append(f"  Result: {str(result)[:200]}")

            elif event_type == "error":
                lines.append(f"  Type: {data.get('error_type', 'unknown')}")
                lines.append(f"  Message: {data.get('error_message', '')}")
                if data.get("recovery"):
                    lines.append(f"  Recovery: {data['recovery']}")

            elif event_type == "termination":
                lines.append(f"  Reason: {data.get('reason', 'unknown')}")
                if data.get("final_output"):
                    lines.append(f"  Final output: {data['final_output'][:200]}")

            if duration is not None:
                lines.append(f"  Duration: {duration:.0f}ms")

        lines.append(f"\n{'='*70}")
        lines.append(f"  End of Trace - {len(self.trace)} events total")
        lines.append(f"{'='*70}")

        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有 trace 记录。"""
        self.trace.clear()
        logger.info("Trace cleared for session: %s", self.session_id)

    def __len__(self) -> int:
        return len(self.trace)

    def __repr__(self) -> str:
        return f"TraceLogger(session={self.session_id}, events={len(self.trace)})"