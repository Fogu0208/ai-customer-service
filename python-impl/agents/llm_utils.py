"""LLM 输出解析工具"""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any] | None:
    """从模型输出中解析 JSON 对象，兼容 ```json 代码块和前后附带的说明文字；解析失败返回 None"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        result = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None
