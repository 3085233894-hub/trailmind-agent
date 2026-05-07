from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# 避免导入 app.agent.graph 时因为 API_KEY 为空直接失败。
# 这里只是测试环境占位，不会真实请求模型。
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("BASE_URL", "https://example.com/api/v1")
os.environ.setdefault("MODEL", "test-model")
os.environ.setdefault("ORS_API_KEY", "test-ors-api-key")


@pytest.fixture
def invoke_tool():
    """
    兼容 LangChain @tool 包装后的 StructuredTool。

    用法：
        result = invoke_tool(geocode_place, place="杭州西湖")
    """
    def _invoke(tool_obj, **kwargs):
        if hasattr(tool_obj, "invoke"):
            return tool_obj.invoke(kwargs)

        return tool_obj(**kwargs)

    return _invoke