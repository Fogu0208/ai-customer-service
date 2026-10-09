"""
意图路由Agent — 用户意图识别与分类
负责分析用户输入，识别出具体的业务意图，为Supervisor提供路由依据。
支持多级意图分类：一级意图(咨询/投诉/办理) -> 二级意图(具体业务)。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.llm_utils import parse_json_object
from tracing.otel_config import trace_agent_call


class IntentCategory(str, Enum):
    """一级意图分类"""
    CONSULTATION = "consultation"       # 咨询类
    COMPLAINT = "complaint"             # 投诉类
    TRANSACTION = "transaction"         # 交易/办理类
    ACCOUNT = "account"                 # 账户类
    COMPLIANCE = "compliance"           # 合规相关
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """意图识别结果"""
    primary_intent: IntentCategory
    secondary_intent: str
    confidence: float
    entities: dict[str, str]
    suggested_agent: str
    parsed: bool = True


ROUTABLE_AGENTS = ("knowledge_rag", "ticket_handler", "compliance_checker")
DEFAULT_AGENT = "knowledge_rag"
HISTORY_TURNS = 4


INTENT_SYSTEM_PROMPT = """你是一个专业的意图识别Agent，负责分析用户的客服消息。

请从以下维度分析用户意图：
1. 一级意图分类: consultation(咨询), complaint(投诉), transaction(交易办理), account(账户), compliance(合规)
2. 二级意图: 具体的业务子类型
3. 置信度: 0.0-1.0
4. 关键实体: 提取订单号、产品名、金额等关键信息
5. 建议路由: knowledge_rag(知识查询), ticket_handler(工单处理), compliance_checker(合规审查)

以JSON格式返回，示例：
{
    "primary_intent": "consultation",
    "secondary_intent": "product_inquiry",
    "confidence": 0.95,
    "entities": {"product": "理财产品A"},
    "suggested_agent": "knowledge_rag"
}

金融场景特殊规则：
- 涉及资金安全、账户异常、欺诈举报 → compliance_checker
- 涉及退款、理赔、开户 → ticket_handler
- 涉及产品咨询、利率查询、政策了解 → knowledge_rag
"""


class IntentRouterAgent:
    """意图路由Agent"""

    def __init__(self, llm: ChatOpenAI):
        self.llm = llm

    @trace_agent_call("intent_router")
    async def classify(self, user_message: str, history: list[BaseMessage] | None = None) -> IntentResult:
        """对用户消息进行意图分类，history 为本轮之前的对话，用于理解指代和追问"""
        content = f"用户消息: {user_message}"
        if history:
            turns = "\n".join(
                f"{'用户' if m.type == 'human' else '客服'}: {m.content}"
                for m in history[-HISTORY_TURNS:]
            )
            content = f"对话上下文（仅供参考）:\n{turns}\n\n{content}"

        messages = [
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=content),
        ]

        response = await self.llm.ainvoke(messages)
        result = parse_json_object(response.content) or {}

        try:
            primary = IntentCategory(result.get("primary_intent", "unknown"))
        except ValueError:
            primary = IntentCategory.UNKNOWN

        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        suggested = result.get("suggested_agent")
        if suggested not in ROUTABLE_AGENTS:
            suggested = DEFAULT_AGENT

        entities = result.get("entities")
        return IntentResult(
            primary_intent=primary,
            secondary_intent=str(result.get("secondary_intent", "unknown")),
            confidence=confidence,
            entities=entities if isinstance(entities, dict) else {},
            suggested_agent=suggested,
            parsed=bool(result),
        )

    @trace_agent_call("intent_router_process")
    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """作为Graph节点处理状态"""
        messages = state.get("messages", [])
        if not messages:
            return state

        last_message = messages[-1].content if messages else ""
        intent_result = await self.classify(last_message)

        return {
            **state,
            "intent": intent_result.suggested_agent,
            "sub_results": {
                **state.get("sub_results", {}),
                "intent_router": {
                    "primary": intent_result.primary_intent.value,
                    "secondary": intent_result.secondary_intent,
                    "confidence": intent_result.confidence,
                    "entities": intent_result.entities,
                },
            },
        }
