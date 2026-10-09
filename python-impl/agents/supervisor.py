"""
Supervisor编排Agent — 中央协调者
负责接收用户请求，调用意图识别Agent得到结构化意图后路由到对应子Agent，汇总结果返回。
采用LangGraph StateGraph实现，通过checkpointer按会话保存图状态以支持多轮对话。
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from agents.intent_router import IntentRouterAgent
from agents.knowledge_rag import KnowledgeRAGAgent
from agents.ticket_handler import TicketHandlerAgent
from agents.compliance_checker import ComplianceCheckerAgent
from memory.working_memory import WorkingMemory
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from tracing.otel_config import trace_agent_call


# ─── 状态定义 ───

class AgentState(TypedDict):
    """Supervisor编排的全局状态"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    intent: str
    sub_results: dict[str, Any]
    compliance_passed: bool
    final_response: str
    current_agent: str
    retry_count: int


# ─── Supervisor节点 ───

class SupervisorNode:
    """Supervisor决策节点"""

    def __init__(self, intent_router: IntentRouterAgent, working_memory: WorkingMemory):
        self.intent_router = intent_router
        self.working_memory = working_memory

    @trace_agent_call("supervisor")
    async def route_decision(self, state: AgentState) -> AgentState:
        """调用意图识别Agent，按结构化结果中的建议路由"""
        messages = state["messages"]
        session_id = state.get("session_id", "default")

        result = await self.intent_router.classify(messages[-1].content, history=messages[:-1])

        self.working_memory.update(session_id, {
            "last_intent": result.suggested_agent,
            "primary_intent": result.primary_intent.value,
            "entities": result.entities,
        })

        return {
            **state,
            "intent": result.suggested_agent,
            "current_agent": "supervisor",
            "sub_results": {
                **state.get("sub_results", {}),
                "intent_router": {
                    "primary": result.primary_intent.value,
                    "secondary": result.secondary_intent,
                    "confidence": result.confidence,
                    "entities": result.entities,
                    "parsed": result.parsed,
                },
            },
        }

    @staticmethod
    def _stringify_result(result: Any) -> str:
        """把子Agent的返回统一成可展示的文本（dict/list 会转成可读字符串）"""
        if result is None:
            return ""
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, (int, float, bool)):
            return str(result)
        if isinstance(result, dict):
            # 优先取语义明确的字段
            for key in ("answer", "response", "content", "result", "message", "summary"):
                if isinstance(result.get(key), str) and result[key].strip():
                    return result[key].strip()
            # 作为来源引用渲染
            if "source" in result and "content" in result:
                return f"[{result['source']}] {result['content']}"
            return json.dumps(result, ensure_ascii=False)
        if isinstance(result, (list, tuple)):
            items = [SupervisorNode._stringify_result(i) for i in result]
            return "\n".join([i for i in items if i])
        return str(result)

    @trace_agent_call("supervisor_synthesize")
    async def synthesize_response(self, state: AgentState) -> AgentState:
        """汇总子Agent结果，生成最终回复"""
        sub_results = state.get("sub_results", {})
        compliance_passed = state.get("compliance_passed", True)

        # 只用于观测、不进最终文案的元数据
        META_KEYS = {"intent_router", "compliance"}

        if not compliance_passed:
            final_response = (
                "抱歉，您的请求涉及敏感内容，已转交人工客服处理。"
                "工单编号已自动生成，请留意后续通知。"
            )
        else:
            result_parts = []
            for agent_name, result in sub_results.items():
                if agent_name in META_KEYS:
                    continue
                text = self._stringify_result(result)
                if text:
                    result_parts.append(text)
            final_response = "\n\n".join(result_parts) if result_parts else "抱歉，暂时无法处理您的请求，请稍后重试。"

        return {
            **state,
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
        }


# ─── 路由函数 ───

def route_to_agent(state: AgentState) -> str:
    """根据意图路由到对应Agent节点；资金安全等风险事件先升级人工，再由知识库给出安全指引"""
    intent = state.get("intent", "knowledge_rag")
    route_map = {
        "knowledge_rag": "knowledge_rag",
        "ticket_handler": "ticket_handler",
        "compliance_checker": "risk_escalation",
    }
    return route_map.get(intent, "knowledge_rag")


def should_check_compliance(state: AgentState) -> str:
    """所有回复都需经过合规审查"""
    return "compliance_check"


# ─── 构建Graph ───

def create_supervisor_graph(
    llm: ChatOpenAI | None = None,
    working_memory: WorkingMemory | None = None,
    short_term_memory: ShortTermMemory | None = None,
    long_term_memory: LongTermMemory | None = None,
    enable_checkpointing: bool = True,
) -> StateGraph:
    """
    构建Supervisor编排的多Agent StateGraph。

    这是整个系统的核心入口，将4个子Agent通过有向图连接起来，
    由Supervisor节点负责路由决策和结果汇总。

    Args:
        llm: 语言模型实例
        working_memory: 工作记忆
        short_term_memory: 短期记忆
        long_term_memory: 长期记忆
        enable_checkpointing: 是否启用检查点（支持断点恢复）
    """
    if llm is None:
        llm = ChatOpenAI(model=os.getenv("MODEL_NAME", "gpt-4o"), temperature=0, timeout=60, max_retries=2)
    if working_memory is None:
        working_memory = WorkingMemory()

    intent_router = IntentRouterAgent(llm)
    supervisor = SupervisorNode(intent_router, working_memory)

    knowledge_agent = KnowledgeRAGAgent(llm, long_term_memory)
    ticket_agent = TicketHandlerAgent(llm)
    compliance_agent = ComplianceCheckerAgent(llm)

    graph = StateGraph(AgentState)

    graph.add_node("supervisor_route", supervisor.route_decision)
    graph.add_node("knowledge_rag", knowledge_agent.process)
    graph.add_node("ticket_handler", ticket_agent.process)
    graph.add_node("risk_escalation", ticket_agent.escalate_risk)
    graph.add_node("compliance_check", compliance_agent.process)
    graph.add_node("synthesize", supervisor.synthesize_response)

    graph.set_entry_point("supervisor_route")

    graph.add_conditional_edges(
        "supervisor_route",
        route_to_agent,
        {
            "knowledge_rag": "knowledge_rag",
            "ticket_handler": "ticket_handler",
            "risk_escalation": "risk_escalation",
        },
    )

    graph.add_edge("risk_escalation", "knowledge_rag")
    graph.add_edge("knowledge_rag", "compliance_check")
    graph.add_edge("ticket_handler", "compliance_check")
    graph.add_edge("compliance_check", "synthesize")
    graph.add_edge("synthesize", END)

    checkpointer = MemorySaver() if enable_checkpointing else None
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled
