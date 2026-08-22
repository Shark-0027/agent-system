"""
LLM 客户端模块。

提供与 OpenAI 兼容 API 交互的 LLMClient 类，支持：
- 多轮对话（chat completion）
- 工具调用（function calling）
- 自动重试与指数退避
- JSON 模式输出
- 流式输出
"""

import os
import time
import json
import logging
from typing import Any, Dict, List, Optional, Union

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletion
from openai import (
    APIError,
    APIConnectionError,
    RateLimitError,
    APITimeoutError,
    AuthenticationError,
)

from .exceptions import ModelCallException

logger = logging.getLogger("agent_runtime.llm")


class LLMClient:
    """LLM 客户端，封装 OpenAI 兼容 API 的调用。

    自动从环境变量读取配置：
        - OPENAI_API_KEY: API 密钥
        - OPENAI_BASE_URL: API 基础 URL（可选）
        - MODEL_NAME: 模型名称

    Attributes:
        api_key: API 密钥。
        base_url: API 基础 URL。
        model_name: 模型名称。
        client: OpenAI 客户端实例。
        max_retries: 最大重试次数。
        request_timeout: 单次请求超时时间（秒）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        max_retries: int = 3,
        request_timeout: float = 120.0,
    ) -> None:
        """初始化 LLM 客户端。

        Args:
            api_key: API 密钥，默认从环境变量 OPENAI_API_KEY 读取。
            base_url: API 基础 URL，默认从环境变量 OPENAI_BASE_URL 读取。
            model_name: 模型名称，默认从环境变量 MODEL_NAME 读取。
            max_retries: 最大重试次数，默认 3 次。
            request_timeout: 单次请求超时时间（秒），默认 120 秒。
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", None)
        self.model_name = model_name or os.environ.get("MODEL_NAME", "gpt-4")
        self.max_retries = max_retries
        self.request_timeout = request_timeout

        if not self.api_key:
            raise ModelCallException(
                "OPENAI_API_KEY not set. Please set the environment variable "
                "or pass api_key explicitly."
            )

        client_kwargs: Dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.request_timeout,
            "max_retries": 0,  # 我们自己管理重试
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)

        logger.info(
            "LLMClient initialized: model=%s, base_url=%s, max_retries=%d",
            self.model_name,
            self.base_url or "default",
            self.max_retries,
        )

    def _calculate_backoff(self, attempt: int) -> float:
        """计算指数退避时间。

        Args:
            attempt: 当前重试次数（从 0 开始）。

        Returns:
            退避等待时间（秒）。
        """
        base_delay = 1.0
        return base_delay * (2 ** attempt)

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否可重试。

        Args:
            error: 发生的异常。

        Returns:
            是否可重试。
        """
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            return True
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIError):
            # 5xx 服务端错误可重试
            if hasattr(error, "status_code") and error.status_code is not None:
                return 500 <= error.status_code < 600
        return False

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        stream: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ChatCompletionMessage:
        """调用模型进行对话补全。

        Args:
            messages: 对话消息列表，每项包含 role 和 content。
            tools: 工具定义列表（OpenAI function calling 格式）。
            temperature: 采样温度，默认 0.7。
            max_tokens: 最大生成 token 数。
            json_mode: 是否启用 JSON 模式输出。
            stream: 是否启用流式输出。
            response_format: 自定义响应格式。
            **kwargs: 其他传递给 OpenAI API 的参数。

        Returns:
            ChatCompletionMessage: 模型返回的消息对象。

        Raises:
            ModelCallException: 当所有重试均失败时抛出。
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    "Chat completion attempt %d/%d, model=%s, messages_count=%d",
                    attempt + 1,
                    self.max_retries,
                    self.model_name,
                    len(messages),
                )

                request_params: Dict[str, Any] = {
                    "model": self.model_name,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": stream,
                    **kwargs,
                }

                if max_tokens is not None:
                    request_params["max_tokens"] = max_tokens

                if json_mode:
                    request_params["response_format"] = {"type": "json_object"}
                elif response_format is not None:
                    request_params["response_format"] = response_format

                if tools:
                    request_params["tools"] = tools
                    request_params["tool_choice"] = "auto"

                if stream:
                    return self._handle_stream(request_params)
                else:
                    response: ChatCompletion = self.client.chat.completions.create(
                        **request_params
                    )

                choice = response.choices[0]
                message = choice.message

                logger.debug(
                    "Chat completion succeeded: finish_reason=%s, "
                    "has_tool_calls=%s, content_length=%d",
                    choice.finish_reason,
                    bool(message.tool_calls),
                    len(message.content or ""),
                )

                return message

            except AuthenticationError as e:
                raise ModelCallException(
                    f"Authentication failed: {e}",
                    attempt=attempt + 1,
                    max_attempts=self.max_retries,
                ) from e

            except Exception as e:
                last_error = e
                if self._is_retryable_error(e) and attempt < self.max_retries - 1:
                    backoff = self._calculate_backoff(attempt)
                    logger.warning(
                        "Chat completion attempt %d failed (retryable): %s. "
                        "Backing off for %.1fs",
                        attempt + 1,
                        e,
                        backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Chat completion attempt %d failed (non-retryable): %s",
                        attempt + 1,
                        e,
                    )
                    break

        raise ModelCallException(
            f"Chat completion failed after {self.max_retries} attempts. "
            f"Last error: {last_error}",
            attempt=self.max_retries,
            max_attempts=self.max_retries,
        ) from last_error

    def _handle_stream(self, request_params: Dict[str, Any]) -> ChatCompletionMessage:
        """处理流式输出。

        Args:
            request_params: API 请求参数。

        Returns:
            合并后的 ChatCompletionMessage 对象。
        """
        stream = self.client.chat.completions.create(**request_params)

        collected_content: str = ""
        collected_tool_calls: List[Dict[str, Any]] = []
        finish_reason: Optional[str] = None

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                collected_content += delta.content

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    # 确保 tool_calls 列表足够长
                    while len(collected_tool_calls) <= tc_delta.index:
                        collected_tool_calls.append(
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        )

                    cur = collected_tool_calls[tc_delta.index]
                    if tc_delta.id:
                        cur["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            cur["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            cur["function"]["arguments"] += tc_delta.function.arguments

            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # 将收集的 tool_calls 转换为 OpenAI 格式
        from openai.types.chat.chat_completion_message_tool_call import (
            ChatCompletionMessageToolCall,
        )
        from openai.types.chat.chat_completion_message_tool_call import Function as ToolFunction

        tool_calls = None
        if collected_tool_calls:
            tool_calls = []
            for tc in collected_tool_calls:
                parsed_call = ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function=ToolFunction(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                )
                tool_calls.append(parsed_call)

        return ChatCompletionMessage(
            role="assistant",
            content=collected_content or None,
            tool_calls=tool_calls,
        )

    def chat_completion_json(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """调用模型并返回 JSON 格式结果。

        Args:
            messages: 对话消息列表。
            **kwargs: 其他传递给 chat_completion 的参数。

        Returns:
            解析后的 JSON 字典。

        Raises:
            ModelCallException: 当模型返回的内容无法解析为 JSON 时抛出。
        """
        message = self.chat_completion(messages, json_mode=True, **kwargs)
        content = message.content or "{}"

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ModelCallException(
                f"Failed to parse JSON response from model: {e}. "
                f"Raw content: {content[:200]}"
            ) from e

    def chat_completion_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ChatCompletionMessage:
        """调用模型并支持工具调用。

        Args:
            messages: 对话消息列表。
            tools: 工具定义列表。
            **kwargs: 其他传递给 chat_completion 的参数。

        Returns:
            ChatCompletionMessage: 模型返回的消息对象。
        """
        return self.chat_completion(messages, tools=tools, **kwargs)