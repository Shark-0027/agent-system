"""
代码仓库分析 MCP Server

提供代码结构分析、行数统计、函数搜索、依赖检查等代码分析工具。
使用 subprocess 和 os 模块实际分析本地文件系统。
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..schema import ToolSchema, make_tool_schema
from ..server import MCPServer


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _is_safe_path(base_path: str, target_path: str) -> bool:
    """检查路径是否在 base_path 内，防止路径穿越。"""
    try:
        base = Path(base_path).resolve()
        target = Path(target_path).resolve()
        return target.is_relative_to(base) or target == base
    except (ValueError, OSError):
        return False


def _scan_files(
    root: str, pattern: str = "*.py", exclude_dirs: Optional[List[str]] = None
) -> List[str]:
    """扫描目录下匹配模式的文件。"""
    if exclude_dirs is None:
        exclude_dirs = [".git", "__pycache__", ".venv", "venv", "node_modules", ".idea"]
    matches = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern):
                matches.append(os.path.join(dirpath, filename))
    return matches


# ---------------------------------------------------------------------------
# RepoAnalysisServer
# ---------------------------------------------------------------------------

class RepoAnalysisServer(MCPServer):
    """代码仓库分析 MCP Server。

    提供代码结构分析、行数统计、函数搜索、依赖检查等工具，
    使用 subprocess 和 os 模块实际分析本地文件。
    """

    def __init__(self) -> None:
        super().__init__(
            name="repo-analysis",
            version="1.0.0",
            description="代码仓库分析服务，支持代码结构分析、行数统计、函数搜索、依赖检查",
            default_timeout=30.0,
        )
        self._register_all_tools()

    def _register_all_tools(self) -> None:
        """注册所有工具。"""

        # --- analyze_code_structure ---
        self.register_tool(
            schema=make_tool_schema(
                name="analyze_code_structure",
                description="分析代码仓库的目录结构和文件组成，返回文件树和按类型分类的统计信息。",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "代码仓库根目录路径",
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "目录树最大深度（默认3）",
                            "default": 3,
                        },
                    },
                    "required": ["repo_path"],
                },
            ),
            handler=self._analyze_code_structure,
            timeout=30.0,
        )

        # --- count_lines ---
        self.register_tool(
            schema=make_tool_schema(
                name="count_lines",
                description="统计代码行数，支持按文件类型过滤。返回总行数、代码行数、注释行数、空行数。",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "代码仓库根目录路径",
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "文件匹配模式，如'*.py'、'*.js'、'*.{py,js}'等",
                            "default": "*.py",
                        },
                    },
                    "required": ["repo_path"],
                },
            ),
            handler=self._count_lines,
            timeout=30.0,
        )

        # --- find_functions ---
        self.register_tool(
            schema=make_tool_schema(
                name="find_functions",
                description="搜索函数定义，支持正则表达式匹配函数名。返回函数名、所在文件、行号和签名。",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "代码仓库根目录路径",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "函数名匹配模式（正则表达式），如'search'、'get_*'等",
                        },
                    },
                    "required": ["repo_path", "pattern"],
                },
            ),
            handler=self._find_functions,
            timeout=30.0,
        )

        # --- check_dependencies ---
        self.register_tool(
            schema=make_tool_schema(
                name="check_dependencies",
                description="检查项目依赖关系，分析 import 语句和 requirements.txt/pyproject.toml 等依赖文件。",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "代码仓库根目录路径",
                        },
                    },
                    "required": ["repo_path"],
                },
            ),
            handler=self._check_dependencies,
            timeout=30.0,
        )

        # --- list_python_files ---
        self.register_tool(
            schema=make_tool_schema(
                name="list_python_files",
                description="列出仓库中所有 Python 文件及其大小。",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "代码仓库根目录路径",
                        },
                    },
                    "required": ["repo_path"],
                },
            ),
            handler=self._list_python_files,
            timeout=15.0,
        )

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _analyze_code_structure(
        self, repo_path: str, max_depth: int = 3
    ) -> Dict[str, Any]:
        """分析代码结构。"""
        path = Path(repo_path)
        if not path.exists():
            return {"error": f"路径不存在: {repo_path}"}
        if not path.is_dir():
            return {"error": f"路径不是目录: {repo_path}"}

        # 文件类型统计
        type_stats: Dict[str, int] = {}
        total_files = 0
        total_dirs = 0

        for root, dirs, files in os.walk(repo_path):
            # 排除隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            total_dirs += len(dirs)
            for f in files:
                total_files += 1
                ext = os.path.splitext(f)[1] or "(no extension)"
                type_stats[ext] = type_stats.get(ext, 0) + 1

            if max_depth > 0:
                depth = root[len(repo_path):].count(os.sep)
                if depth >= max_depth:
                    dirs[:] = []

        # 目录树（限定深度）
        tree = self._build_tree(repo_path, max_depth)

        return {
            "repo_path": repo_path,
            "total_files": total_files,
            "total_directories": total_dirs,
            "file_types": dict(
                sorted(type_stats.items(), key=lambda x: x[1], reverse=True)
            ),
            "directory_tree": tree,
        }

    def _build_tree(self, root: str, max_depth: int, current_depth: int = 0) -> Dict[str, Any]:
        """递归构建目录树。"""
        path = Path(root)
        result: Dict[str, Any] = {
            "name": path.name or root,
            "type": "directory",
            "children": [],
        }
        if current_depth >= max_depth:
            result["children"] = ["..."]
            return result

        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return result

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                result["children"].append(
                    self._build_tree(str(entry), max_depth, current_depth + 1)
                )
            else:
                result["children"].append({
                    "name": entry.name,
                    "type": "file",
                    "size_bytes": entry.stat().st_size if entry.exists() else 0,
                })

        return result

    def _count_lines(
        self, repo_path: str, file_pattern: str = "*.py"
    ) -> Dict[str, Any]:
        """统计代码行数。"""
        path = Path(repo_path)
        if not path.exists():
            return {"error": f"路径不存在: {repo_path}"}

        files = _scan_files(repo_path, file_pattern)
        total_lines = 0
        total_code = 0
        total_comments = 0
        total_blank = 0
        per_file: List[Dict[str, Any]] = []

        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except (IOError, OSError):
                continue

            file_lines = len(lines)
            file_code = 0
            file_comments = 0
            file_blank = 0

            ext = os.path.splitext(filepath)[1]
            in_multiline = False

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    file_blank += 1
                    continue

                # Python 注释
                if ext == ".py":
                    if in_multiline:
                        file_comments += 1
                        if '"""' in stripped or "'''" in stripped:
                            in_multiline = False
                        continue
                    if stripped.startswith("#"):
                        file_comments += 1
                        continue
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        file_comments += 1
                        if stripped.count('"""') + stripped.count("'''") < 2:
                            in_multiline = True
                        continue
                    file_code += 1
                else:
                    # 通用：以 # 或 // 开头视为注释
                    if stripped.startswith("#") or stripped.startswith("//"):
                        file_comments += 1
                    else:
                        file_code += 1

            total_lines += file_lines
            total_code += file_code
            total_comments += file_comments
            total_blank += file_blank

            per_file.append({
                "file": os.path.relpath(filepath, repo_path),
                "total": file_lines,
                "code": file_code,
                "comments": file_comments,
                "blank": file_blank,
            })

        return {
            "repo_path": repo_path,
            "file_pattern": file_pattern,
            "files_scanned": len(files),
            "total_lines": total_lines,
            "code_lines": total_code,
            "comment_lines": total_comments,
            "blank_lines": total_blank,
            "per_file": per_file[:50],  # 限制返回数量
        }

    def _find_functions(
        self, repo_path: str, pattern: str
    ) -> Dict[str, Any]:
        """搜索函数定义。"""
        path = Path(repo_path)
        if not path.exists():
            return {"error": f"路径不存在: {repo_path}"}

        py_files = _scan_files(repo_path, "*.py")
        regex = re.compile(pattern, re.IGNORECASE)
        results: List[Dict[str, Any]] = []

        for filepath in py_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except (IOError, OSError):
                continue

            try:
                tree = ast.parse(source, filename=filepath)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if regex.search(node.name):
                        # 构建函数签名
                        args = []
                        for arg in node.args.args:
                            arg_str = arg.arg
                            if arg.annotation:
                                arg_str += f": {ast.unparse(arg.annotation)}"
                            args.append(arg_str)
                        signature = f"def {node.name}({', '.join(args)})"

                        results.append({
                            "name": node.name,
                            "file": os.path.relpath(filepath, repo_path),
                            "line": node.lineno,
                            "signature": signature,
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                        })

        return {
            "repo_path": repo_path,
            "pattern": pattern,
            "total_found": len(results),
            "functions": results,
        }

    def _check_dependencies(self, repo_path: str) -> Dict[str, Any]:
        """检查依赖关系。"""
        path = Path(repo_path)
        if not path.exists():
            return {"error": f"路径不存在: {repo_path}"}

        result: Dict[str, Any] = {
            "repo_path": repo_path,
            "dependency_files": [],
            "third_party_imports": [],
            "internal_imports": [],
        }

        # 查找依赖文件
        dep_files = ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"]
        for df in dep_files:
            df_path = os.path.join(repo_path, df)
            if os.path.isfile(df_path):
                result["dependency_files"].append(df)

        # 解析 requirements.txt
        req_path = os.path.join(repo_path, "requirements.txt")
        if os.path.isfile(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            result["third_party_imports"].append(line)
            except (IOError, OSError):
                pass

        # 分析所有 Python 文件的 import
        py_files = _scan_files(repo_path, "*.py")
        internal_modules: set = set()
        third_party: set = set()

        # 标准库列表
        std_libs = {
            "os", "sys", "re", "json", "math", "time", "datetime", "collections",
            "typing", "abc", "pathlib", "logging", "subprocess", "threading",
            "asyncio", "unittest", "itertools", "functools", "hashlib", "random",
            "io", "csv", "xml", "html", "http", "urllib", "socket", "ssl",
            "email", "base64", "struct", "pickle", "copy", "enum", "dataclasses",
            "argparse", "configparser", "textwrap", "shutil", "tempfile", "glob",
            "fnmatch", "traceback", "warnings", "contextlib", "inspect", "ast",
        }

        for filepath in py_files:
            rel_path = os.path.relpath(filepath, repo_path)
            module_name = rel_path.replace(os.sep, ".").replace(".py", "")
            internal_modules.add(module_name)

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except (IOError, OSError):
                continue

            try:
                tree = ast.parse(source, filename=filepath)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_level = alias.name.split(".")[0]
                        if top_level not in std_libs:
                            third_party.add(top_level)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_level = node.module.split(".")[0]
                        if top_level not in std_libs:
                            third_party.add(top_level)

        result["third_party_imports"] = sorted(third_party)
        result["internal_modules"] = sorted(internal_modules)
        result["internal_module_count"] = len(internal_modules)

        return result

    def _list_python_files(self, repo_path: str) -> Dict[str, Any]:
        """列出所有 Python 文件。"""
        path = Path(repo_path)
        if not path.exists():
            return {"error": f"路径不存在: {repo_path}"}

        files = _scan_files(repo_path, "*.py")
        file_list = []
        for filepath in files:
            try:
                size = os.path.getsize(filepath)
            except OSError:
                size = 0
            file_list.append({
                "path": os.path.relpath(filepath, repo_path),
                "size_bytes": size,
                "size_kb": round(size / 1024, 2),
            })

        file_list.sort(key=lambda x: x["size_bytes"], reverse=True)

        return {
            "repo_path": repo_path,
            "total_python_files": len(file_list),
            "files": file_list,
        }