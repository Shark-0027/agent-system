"""项目级 pytest 配置。

项目顶层包名为 ``code``，与 Python 标准库自带模块 ``code`` 同名冲突。
在 pytest 收集测试之前，先把项目根加入 ``sys.path`` 并提前导入项目包，
避免 ``import code.workbench.csv_agent`` 命中的是标准库的 ``code`` 模块。
"""
import os
import sys

_here = os.path.abspath(os.path.dirname(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import code.workbench.csv_agent  # noqa: F401, E402