"""
合规审查Agent — 金融/电商场景合规检查
负责对所有Agent的回复进行合规审查，包括：
- 敏感词检测
- PII（个人身份信息）保护
- 金融合规用语检查
- 越权承诺检测
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.llm_utils import parse_json_object
from tracing.otel_config import trace_agent_call


logger = logging.getLogger(__name__)


@dataclass
class ComplianceResult:
    """合规审查结果"""
    passed: bool
    risk_level: str  # low, medium, high, critical
    violations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    sanitized_content: str = ""
    llm_reviewed: bool = False


# 格式特征明确，命中即判定泄露
STRICT_PII_PATTERNS = {
    "phone": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "id_card": r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![\dXx])",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
}

# 与订单号、流水号等长数字无法区分，只作为疑似项交给 LLM 复核
AMBIGUOUS_PII_PATTERNS = {
    "bank_card": r"(?<!\d)\d{16,19}(?!\d)",
}

SENSITIVE_PATTERNS = {**STRICT_PII_PATTERNS, **AMBIGUOUS_PII_PATTERNS}

PII_LABELS = {"phone": "手机号", "id_card": "身份证号", "bank_card": "银行卡号", "email": "邮箱地址"}

FORBIDDEN_TERMS = [
    "保证收益", "稳赚不赔", "零风险", "保本保息",
    "最高收益", "预期收益率", "承诺回报",
    "内部消息", "内幕", "暗箱操作",
]

RISK_LEVELS = ("low", "medium", "high", "critical")

COMPLIANCE_SYSTEM_PROMPT = """你是一个金融合规审查Agent，负责审查客服回复内容的合规性。

审查维度：
1. 是否包含违规金融用语（如"保证收益"、"零风险"等）
2. 是否泄露用户PII信息（手机号、身份证号、银行卡号）；仅展示尾号后4位属于正常脱敏展示，不算泄露
3. 是否存在越权承诺（如擅自承诺退款/赔偿金额）
4. 是否符合金融监管要求（风险提示、免责声明）
5. 是否包含歧视性、侮辱性内容

请以JSON格式返回审查结果：
{
    "passed": true/false,
    "risk_level": "low|medium|high|critical",
    "violations": ["违规项描述"],
    "suggestions": ["修改建议"]
}
"""

RULE_HINT_TEMPLATE = """
规则引擎在这段内容中标记了以下疑似问题，请结合上下文判断是否真正违规：
{hints}
注意：词语出现在否定、风险警示或反诈提醒的语境中不算违规；订单号、流水号等长数字不属于银行卡号。
"""


class ComplianceCheckerAgent:
    """合规审查Agent"""

    def __init__(self, llm: ChatOpenAI):
        self.llm = llm

    def _rule_hits(self, content: str) -> tuple[list[str], list[str]]:
        """基于规则的快速检查（不依赖LLM，低延迟），返回 (确定违规项, 需复核的疑似项)"""
        confirmed, suspected = [], []

        for pii_type, pattern in STRICT_PII_PATTERNS.items():
            if re.search(pattern, content):
                confirmed.append(f"检测到PII信息泄露: {PII_LABELS[pii_type]}")

        for pii_type, pattern in AMBIGUOUS_PII_PATTERNS.items():
            if re.search(pattern, content):
                suspected.append(f"疑似PII信息泄露: {PII_LABELS[pii_type]}")

        for term in FORBIDDEN_TERMS:
            if term in content:
                suspected.append(f"包含违规金融用语: '{term}'")

        return confirmed, suspected

    def _mask_pii(self, content: str) -> str:
        """对PII信息进行脱敏处理"""
        masked = content
        for pii_type, pattern in SENSITIVE_PATTERNS.items():
            def _mask_match(match):
                text = match.group()
                if len(text) <= 4:
                    return "****"
                return text[:3] + "*" * (len(text) - 6) + text[-3:]
            masked = re.sub(pattern, _mask_match, masked)
        return masked

    @trace_agent_call("compliance_rule_check")
    async def rule_check(self, content: str) -> ComplianceResult:
        """仅用规则引擎审查：任何命中（含疑似项）都判定为不通过"""
        confirmed, suspected = self._rule_hits(content)
        violations = confirmed + suspected
        sanitized = self._mask_pii(content)

        if not violations:
            return ComplianceResult(
                passed=True,
                risk_level="low",
                sanitized_content=sanitized,
            )

        has_pii = any("PII" in v for v in violations)
        has_forbidden = any("违规金融用语" in v for v in violations)

        if has_pii and has_forbidden:
            risk_level = "critical"
        elif has_pii or has_forbidden:
            risk_level = "high"
        else:
            risk_level = "medium"

        return ComplianceResult(
            passed=False,
            risk_level=risk_level,
            violations=violations,
            sanitized_content=sanitized,
        )

    @trace_agent_call("compliance_llm_check")
    async def llm_check(self, content: str, rule_hints: list[str] | None = None) -> ComplianceResult:
        """
        LLM深度合规审查（处理规则引擎无法覆盖的场景）。
        rule_hints 为规则引擎的疑似命中项；LLM 不可用时，有疑似项则保守拦截，否则放行。
        """
        prompt = f"请审查以下客服回复内容的合规性：\n\n{content}"
        if rule_hints:
            prompt += RULE_HINT_TEMPLATE.format(hints="\n".join(f"- {h}" for h in rule_hints))

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        result = None
        try:
            response = await self.llm.ainvoke(messages)
            result = parse_json_object(response.content)
        except Exception as e:
            logger.warning("LLM 合规审查调用失败: %s", e)

        if result is None:
            return ComplianceResult(
                passed=not rule_hints,
                risk_level="high" if rule_hints else "low",
                violations=list(rule_hints or []),
                sanitized_content=self._mask_pii(content),
            )

        risk_level = result.get("risk_level", "low")
        return ComplianceResult(
            passed=bool(result.get("passed", True)),
            risk_level=risk_level if risk_level in RISK_LEVELS else "medium",
            violations=list(result.get("violations") or []),
            suggestions=list(result.get("suggestions") or []),
            sanitized_content=self._mask_pii(content),
            llm_reviewed=True,
        )

    @trace_agent_call("compliance_full_check")
    async def full_check(self, content: str) -> ComplianceResult:
        """
        两阶段合规审查：
        1. 规则引擎快速检查（毫秒级）：手机号、身份证号等格式明确的PII命中即拦截，不再调用LLM
        2. 其余内容交给LLM审查，规则引擎的疑似命中（违规用语、疑似银行卡号）作为提示，
           由LLM结合语境判断，避免否定句、警示语和订单号被误杀
        """
        confirmed, suspected = self._rule_hits(content)

        if confirmed:
            return ComplianceResult(
                passed=False,
                risk_level="critical" if suspected else "high",
                violations=confirmed + suspected,
                sanitized_content=self._mask_pii(content),
            )

        return await self.llm_check(content, rule_hints=suspected)

    @trace_agent_call("compliance_process")
    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """作为Graph节点处理状态"""
        sub_results = state.get("sub_results", {})

        content_to_check = ""
        for agent_name, result in sub_results.items():
            if isinstance(result, str):
                content_to_check += result + "\n"

        if not content_to_check.strip():
            return {**state, "compliance_passed": True}

        compliance_result = await self.full_check(content_to_check)

        if not compliance_result.passed:
            for key in sub_results:
                if isinstance(sub_results[key], str):
                    sub_results[key] = compliance_result.sanitized_content

        return {
            **state,
            "compliance_passed": compliance_result.passed,
            "sub_results": {
                **sub_results,
                "compliance": {
                    "passed": compliance_result.passed,
                    "risk_level": compliance_result.risk_level,
                    "violations": compliance_result.violations,
                },
            },
        }
