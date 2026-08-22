"""
文档检索 MCP Server

提供文档索引、语义搜索、全文获取、主题列表等文档检索服务。
使用简单的 TF-IDF 和关键词匹配实现搜索功能。
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..schema import ToolSchema, make_tool_schema
from ..server import MCPServer


# ---------------------------------------------------------------------------
# 简易 TF-IDF 搜索引擎
# ---------------------------------------------------------------------------

class _SimpleTFIDF:
    """简易 TF-IDF 搜索引擎。

    实现词频-逆文档频率（TF-IDF）算法，用于文档检索。
    """

    def __init__(self) -> None:
        self._documents: Dict[str, Dict[str, Any]] = {}
        """doc_id -> {title, content, path, topics}"""

        self._idf: Dict[str, float] = {}
        """term -> IDF 值"""

        self._tf: Dict[str, Dict[str, float]] = {}
        """doc_id -> {term -> TF 值}"""

        self._topics: Set[str] = set()
        """所有文档主题集合"""

        self._stop_words: Set[str] = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
            "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "about", "or", "and",
            "not", "no", "but", "if", "than", "then", "so", "we", "you", "he",
            "she", "it", "they", "this", "that", "these", "those", "which", "who",
            "whom", "whose", "what", "when", "where", "why", "how", "all", "any",
            "both", "each", "few", "more", "most", "other", "some", "such", "only",
            "own", "same", "just", "very", "too", "also", "now", "here", "there",
        }

    def index_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        path: str = "",
        topics: Optional[List[str]] = None,
    ) -> None:
        """索引一篇文档。"""
        self._documents[doc_id] = {
            "title": title,
            "content": content,
            "path": path,
            "topics": topics or [],
        }
        if topics:
            self._topics.update(topics)

        # 计算 TF
        tokens = self._tokenize(content)
        total = len(tokens) if tokens else 1
        counter = Counter(tokens)
        self._tf[doc_id] = {term: count / total for term, count in counter.items()}

    def build_index(self) -> None:
        """构建 IDF 索引。"""
        doc_count = len(self._documents)
        if doc_count == 0:
            return

        # 计算每个词的文档频率
        df: Dict[str, int] = defaultdict(int)
        for doc_id, tf_map in self._tf.items():
            for term in tf_map:
                df[term] += 1

        # 计算 IDF
        self._idf = {
            term: math.log((doc_count + 1) / (freq + 1)) + 1.0
            for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索文档。"""
        if not self._documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # 计算查询向量
        query_counter = Counter(query_tokens)
        query_total = len(query_tokens)

        # 计算每个文档的 TF-IDF 得分
        scores: List[Tuple[str, float]] = []
        for doc_id, tf_map in self._tf.items():
            score = 0.0
            for term, count in query_counter.items():
                if term in tf_map and term in self._idf:
                    tf = tf_map[term]
                    idf = self._idf[term]
                    qtf = count / query_total
                    score += tf * idf * qtf
            if score > 0:
                scores.append((doc_id, score))

        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_k]

        results = []
        for doc_id, score in top:
            doc = self._documents[doc_id]
            results.append({
                "doc_id": doc_id,
                "title": doc["title"],
                "path": doc["path"],
                "topics": doc["topics"],
                "relevance_score": round(score, 4),
                "snippet": self._get_snippet(doc["content"], query_tokens),
            })

        return results

    def _tokenize(self, text: str) -> List[str]:
        """分词（中文+英文）。

        中文使用 bigram（双字词）分词，英文按单词分词。
        """
        tokens: List[str] = []
        # 中文按 bigram 分词，保留语义信息
        chinese_seq = re.findall(r"[\u4e00-\u9fff]+", text)
        for seq in chinese_seq:
            if len(seq) == 1:
                tokens.append(seq)
            else:
                for i in range(len(seq) - 1):
                    tokens.append(seq[i:i + 2])
        # 英文单词
        english_words = re.findall(r"[a-zA-Z_]+", text)
        tokens.extend(w.lower() for w in english_words if len(w) > 1)
        # 数字
        numbers = re.findall(r"\d+", text)
        tokens.extend(numbers)
        # 过滤停用词
        tokens = [t for t in tokens if t not in self._stop_words]
        return tokens

    def _get_snippet(
        self, content: str, query_tokens: List[str], max_length: int = 200
    ) -> str:
        """获取搜索片段。"""
        content_lower = content.lower()
        best_pos = 0
        best_score = 0

        # 找包含最多查询词的位置
        for i in range(0, len(content), 50):
            window = content_lower[i:i + max_length]
            score = sum(1 for t in query_tokens if t.lower() in window)
            if score > best_score:
                best_score = score
                best_pos = i

        start = max(0, best_pos - 20)
        end = min(len(content), best_pos + max_length)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档全文。"""
        return self._documents.get(doc_id)

    def get_topics(self) -> List[str]:
        """获取所有主题。"""
        return sorted(self._topics)

    @property
    def document_count(self) -> int:
        return len(self._documents)


# ---------------------------------------------------------------------------
# 模拟文档数据
# ---------------------------------------------------------------------------

_MOCK_DOCS = [
    {
        "id": "doc_001",
        "title": "Python 编程入门指南",
        "path": "docs/python_intro.md",
        "topics": ["Python", "编程基础", "入门"],
        "content": (
            "Python 是一种高级编程语言，以其简洁的语法和强大的功能而闻名。"
            "本指南面向零基础学习者，从环境搭建开始，逐步介绍 Python 的基本语法、"
            "数据类型、控制流程、函数定义、面向对象编程等核心概念。"
            "Python 广泛应用于 Web 开发、数据科学、人工智能、自动化运维等领域。"
            "学习 Python 是进入编程世界的最佳选择之一。"
        ),
    },
    {
        "id": "doc_002",
        "title": "深度学习入门与实践",
        "path": "docs/deep_learning.md",
        "topics": ["深度学习", "AI", "神经网络"],
        "content": (
            "深度学习是机器学习的一个子领域，使用多层神经网络从数据中学习特征表示。"
            "本教程涵盖卷积神经网络（CNN）、循环神经网络（RNN）、Transformer 架构等核心技术。"
            "实践部分包括使用 PyTorch 和 TensorFlow 框架实现图像分类、文本生成等任务。"
            "深度学习在计算机视觉、自然语言处理、推荐系统等领域取得了突破性进展。"
        ),
    },
    {
        "id": "doc_003",
        "title": "MCP 协议规范",
        "path": "docs/mcp_spec.md",
        "topics": ["MCP", "协议", "工具系统"],
        "content": (
            "Model Context Protocol（MCP）是一种用于 AI 模型与外部工具交互的协议规范。"
            "MCP 定义了工具发现、参数传递、结果返回的标准接口。"
            "核心组件包括 MCPServer、MCPClient、ToolRegistry 和 ToolRouter。"
            "通过 MCP 协议，AI 模型可以动态发现和调用各种工具，实现复杂任务的自动化。"
            "MCP Server 负责注册和管理工具，MCP Client 负责连接和调用远端的工具服务。"
        ),
    },
    {
        "id": "doc_004",
        "title": "Web 全栈开发路线图",
        "path": "docs/web_fullstack.md",
        "topics": ["Web开发", "全栈", "前端", "后端"],
        "content": (
            "Web 全栈开发涵盖前端界面开发、后端服务开发、数据库管理等多个方面。"
            "前端技术栈包括 HTML、CSS、JavaScript，以及 React、Vue 等现代框架。"
            "后端技术栈包括 Node.js、Python Django/Flask、Go 等。"
            "数据库方面需要掌握 MySQL、PostgreSQL、MongoDB 等。"
            "全栈开发者需要具备完整的项目交付能力，从需求分析到部署上线。"
        ),
    },
    {
        "id": "doc_005",
        "title": "数据结构与算法精讲",
        "path": "docs/algorithms.md",
        "topics": ["算法", "数据结构", "面试"],
        "content": (
            "数据结构与算法是计算机科学的核心基础，也是技术面试的重点考察内容。"
            "本教程系统讲解数组、链表、栈、队列、树、图、哈希表等数据结构，"
            "以及排序、搜索、动态规划、贪心、回溯等经典算法。"
            "每个知识点都配有 Python 实现和 LeetCode 实战题目。"
            "掌握这些知识对于写出高效、优雅的代码至关重要。"
        ),
    },
    {
        "id": "doc_006",
        "title": "计算机网络基础",
        "path": "docs/networking.md",
        "topics": ["网络", "TCP/IP", "HTTP"],
        "content": (
            "计算机网络是连接全球的计算设备的基础设施。"
            "本教程从 OSI 七层模型和 TCP/IP 协议栈开始，逐步讲解物理层、数据链路层、"
            "网络层、传输层和应用层的核心协议。"
            "重点内容包括 IP 地址、路由算法、TCP 三次握手、HTTP/HTTPS 协议、DNS 解析等。"
            "理解网络原理对于构建分布式系统和排查网络问题至关重要。"
        ),
    },
    {
        "id": "doc_007",
        "title": "Git 版本控制实战",
        "path": "docs/git_guide.md",
        "topics": ["Git", "版本控制", "协作"],
        "content": (
            "Git 是目前最流行的分布式版本控制系统。"
            "本指南涵盖 Git 的基本操作、分支管理、合并冲突解决、远程仓库协作等核心技能。"
            "还包括 Git Flow 工作流、Pull Request 流程、Code Review 最佳实践。"
            "掌握 Git 是团队协作开发的基本要求。"
        ),
    },
    {
        "id": "doc_008",
        "title": "Linux 系统管理基础",
        "path": "docs/linux_basics.md",
        "topics": ["Linux", "系统管理", "运维"],
        "content": (
            "Linux 是服务器端最主流的操作系统。"
            "本教程介绍 Linux 文件系统、用户管理、权限控制、进程管理、"
            "Shell 脚本编程、网络配置、软件包管理等核心知识。"
            "还包括常用的运维工具如 systemd、cron、rsync、SSH 等。"
            "对于后端开发者和运维工程师来说，Linux 技能是必备的。"
        ),
    },
    {
        "id": "doc_009",
        "title": "数据库系统原理",
        "path": "docs/database.md",
        "topics": ["数据库", "SQL", "MySQL"],
        "content": (
            "数据库系统是现代应用的核心组件。"
            "本教程涵盖关系型数据库（MySQL、PostgreSQL）的 SQL 查询、索引优化、"
            "事务管理、数据库设计范式等内容。"
            "同时介绍 NoSQL 数据库（MongoDB、Redis）的使用场景和基本操作。"
            "数据库性能优化是后端开发中的重要技能。"
        ),
    },
    {
        "id": "doc_010",
        "title": "红岩网校 AI 部门考核指南",
        "path": "docs/ai_dept_assessment.md",
        "topics": ["红岩网校", "AI", "考核", "MCP"],
        "content": (
            "红岩网校 AI 部门考核项目旨在考察候选人的技术能力和工程素养。"
            "考核选题包括 MCP 工具系统、Agent Runtime、智能任务编排等方向。"
            "候选人需要完成完整的代码实现，包括模块设计、接口定义、单元测试和文档。"
            "考核标准包括代码质量、架构设计、功能完整性和创新能力。"
            "MCP（Model Context Protocol）是本次考核的核心主题之一，"
            "要求实现工具注册、发现、调用、路由等完整功能。"
        ),
    },
]


# ---------------------------------------------------------------------------
# DocSearchServer
# ---------------------------------------------------------------------------

class DocSearchServer(MCPServer):
    """文档检索 MCP Server。

    提供文档索引、语义搜索、全文获取、主题列表等文档检索服务。
    使用 TF-IDF 算法实现文档搜索。
    """

    def __init__(self) -> None:
        super().__init__(
            name="doc-search",
            version="1.0.0",
            description="文档检索服务，支持文档索引、语义搜索、全文获取、主题列表",
            default_timeout=15.0,
        )
        self._engine = _SimpleTFIDF()
        self._register_all_tools()

    def _register_all_tools(self) -> None:
        """注册所有工具。"""

        # --- index_documents ---
        self.register_tool(
            schema=make_tool_schema(
                name="index_documents",
                description="索引文档目录，将目录中的文档加入搜索引擎。支持从本地目录读取或使用内置示例数据。",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "文档目录路径，如果为空则使用内置示例数据",
                            "default": "",
                        },
                    },
                },
            ),
            handler=self._index_documents,
            timeout=30.0,
        )

        # --- search_docs ---
        self.register_tool(
            schema=make_tool_schema(
                name="search_docs",
                description="语义搜索文档，使用 TF-IDF 算法搜索最相关的文档。返回文档标题、片段和相关性分数。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询文本",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量（默认5）",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._search_docs,
            timeout=10.0,
        )

        # --- get_document ---
        self.register_tool(
            schema=make_tool_schema(
                name="get_document",
                description="获取文档全文内容，返回文档的标题、内容、主题和元数据。",
                parameters={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "string",
                            "description": "文档唯一标识符",
                        },
                    },
                    "required": ["doc_id"],
                },
            ),
            handler=self._get_document,
            timeout=5.0,
        )

        # --- list_topics ---
        self.register_tool(
            schema=make_tool_schema(
                name="list_topics",
                description="列出所有文档主题，返回主题列表和每个主题的文档数量。",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            handler=self._list_topics,
            timeout=5.0,
        )

        # --- list_documents ---
        self.register_tool(
            schema=make_tool_schema(
                name="list_documents",
                description="列出所有已索引的文档摘要，返回文档ID、标题和主题。",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            handler=self._list_documents,
            timeout=5.0,
        )

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _index_documents(self, directory: str = "") -> Dict[str, Any]:
        """索引文档。"""
        count = 0

        if directory and os.path.isdir(directory):
            # 从本地目录索引
            for root, _, files in os.walk(directory):
                for filename in files:
                    if filename.endswith((".md", ".txt", ".rst", ".py")):
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                        except (IOError, OSError):
                            continue

                        doc_id = f"local_{count}"
                        doc_path = os.path.relpath(filepath, directory)
                        self._engine.index_document(
                            doc_id=doc_id,
                            title=filename,
                            content=content,
                            path=doc_path,
                            topics=[],
                        )
                        count += 1
        else:
            # 使用内置示例数据
            for doc in _MOCK_DOCS:
                self._engine.index_document(
                    doc_id=doc["id"],
                    title=doc["title"],
                    content=doc["content"],
                    path=doc["path"],
                    topics=doc["topics"],
                )
                count += 1

        # 构建 IDF 索引
        self._engine.build_index()

        return {
            "indexed_count": count,
            "total_documents": self._engine.document_count,
            "source": directory if directory else "内置示例数据",
        }

    def _search_docs(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """搜索文档。"""
        # 确保索引已构建
        if self._engine.document_count == 0:
            self._index_documents()

        if self._engine.document_count == 0:
            return {"query": query, "total": 0, "results": []}

        results = self._engine.search(query, top_k)

        return {
            "query": query,
            "total": len(results),
            "results": results,
        }

    def _get_document(self, doc_id: str) -> Dict[str, Any]:
        """获取文档全文。"""
        doc = self._engine.get_document(doc_id)
        if not doc:
            return {
                "found": False,
                "doc_id": doc_id,
                "message": f"文档不存在: {doc_id}",
            }

        return {
            "found": True,
            "doc_id": doc_id,
            "title": doc["title"],
            "path": doc["path"],
            "topics": doc["topics"],
            "content": doc["content"],
            "content_length": len(doc["content"]),
        }

    def _list_topics(self) -> Dict[str, Any]:
        """列出所有主题及文档数。"""
        if self._engine.document_count == 0:
            self._index_documents()

        topic_counts: Dict[str, int] = defaultdict(int)
        for doc_id, doc in self._engine._documents.items():
            for topic in doc["topics"]:
                topic_counts[topic] += 1

        topics = [
            {"topic": topic, "document_count": count}
            for topic, count in sorted(
                topic_counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

        return {
            "total_topics": len(topics),
            "topics": topics,
        }

    def _list_documents(self) -> Dict[str, Any]:
        """列出所有文档摘要。"""
        if self._engine.document_count == 0:
            self._index_documents()

        docs = []
        for doc_id, doc in self._engine._documents.items():
            docs.append({
                "doc_id": doc_id,
                "title": doc["title"],
                "path": doc["path"],
                "topics": doc["topics"],
                "content_length": len(doc["content"]),
            })

        docs.sort(key=lambda x: x["title"])

        return {
            "total_documents": len(docs),
            "documents": docs,
        }