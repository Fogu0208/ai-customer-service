"""
离线评测 — 路由准确率 / 知识检索命中率 / 合规审查效果

在 python-impl 目录下运行：
    python -m eval.run_eval                          # 跑全部评测
    python -m eval.run_eval --suite retrieval        # 只跑某一项（routing / retrieval / compliance）
    python -m eval.run_eval --limit 10               # 每项只取前 10 条，快速冒烟

结果输出到终端，并保存到 eval/results/ 下的 Markdown 报告和 JSON 明细。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.compliance_checker import ComplianceCheckerAgent
from agents.intent_router import IntentRouterAgent
from agents.knowledge_rag import KnowledgeRAGAgent
from agents.supervisor import SupervisorNode
from memory.long_term import LongTermMemory
from memory.working_memory import WorkingMemory


EVAL_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVAL_DIR / "datasets"
RESULT_DIR = EVAL_DIR / "results"
KB_DIR = EVAL_DIR.parent / "data" / "knowledge_base"

ROUTES = ["knowledge_rag", "ticket_handler", "compliance_checker"]


# ─── 工具函数 ───

def load_jsonl(name: str, limit: int | None) -> list[dict]:
    with open(DATASET_DIR / name, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return rows[:limit] if limit else rows


async def run_all(items: list, worker: Callable[[int, Any], Awaitable[dict]], concurrency: int) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def guarded(i: int, item: Any) -> dict:
        nonlocal done
        async with semaphore:
            result = await worker(i, item)
        done += 1
        print(f"\r  进度 {done}/{len(items)}", end="", flush=True)
        return result

    results = await asyncio.gather(*(guarded(i, item) for i, item in enumerate(items)))
    print()
    return list(results)


async def timed(coro: Awaitable[Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = await coro
    return result, (time.perf_counter() - start) * 1000


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def percentile(values: list[float], q: float) -> float:
    """耗时用分位数而不是均值，避免个别超时重试的请求拉高结果"""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]


def latency_cells(values: list[float]) -> list[str]:
    return [f"{percentile(values, 0.5):.0f}", f"{percentile(values, 0.9):.0f}"]


# ─── 路由评测 ───

# 接入意图识别Agent之前，Supervisor 直接让模型输出 Agent 名称的路由方式，保留作对比基线
BASELINE_ROUTING_PROMPT = """你是一个智能客服系统的Supervisor（主管编排Agent）。
你的职责是：
1. 分析用户意图，决定分发给哪个子Agent处理
2. 汇总子Agent的处理结果，生成最终回复
3. 确保所有回复都经过合规审查

可用的子Agent：
- intent_router: 意图识别和分类
- knowledge_rag: 知识库检索和回答
- ticket_handler: 工单创建和查询
- compliance_checker: 合规审查和敏感词检测

根据用户消息，决定下一步路由到哪个Agent。
"""


async def baseline_route(llm: ChatOpenAI, query: str) -> str:
    response = await llm.ainvoke([
        SystemMessage(content=BASELINE_ROUTING_PROMPT),
        SystemMessage(content="当前工作记忆上下文: {}"),
        HumanMessage(content=query),
        HumanMessage(content=(
            "请分析用户的最新消息，返回应该路由到的Agent名称。"
            "只返回以下之一: knowledge_rag, ticket_handler, compliance_checker"
        )),
    ])
    intent = response.content.strip().lower()
    return intent if intent in ROUTES else "knowledge_rag"


async def eval_routing(llm: ChatOpenAI, cases: list[dict], concurrency: int) -> tuple[str, dict]:
    supervisor = SupervisorNode(IntentRouterAgent(llm), WorkingMemory())
    methods = ["prompt_baseline", "supervisor"]
    labels = {"prompt_baseline": "直接 prompt 路由(基线)", "supervisor": "结构化意图识别(当前)"}

    async def worker(i: int, case: dict) -> dict:
        state = {"messages": [HumanMessage(content=case["query"])], "session_id": f"eval-routing-{i}"}
        sup_state, sup_ms = await timed(supervisor.route_decision(state))
        base_pred, base_ms = await timed(baseline_route(llm, case["query"]))

        return {
            **case,
            "supervisor": sup_state["intent"],
            "supervisor_ms": sup_ms,
            "supervisor_parse_failed": not sup_state["sub_results"]["intent_router"]["parsed"],
            "supervisor_intent": sup_state["sub_results"]["intent_router"],
            "prompt_baseline": base_pred,
            "prompt_baseline_ms": base_ms,
        }

    results = await run_all(cases, worker, concurrency)

    summary: dict[str, Any] = {}
    rows = []
    per_class_rows = []
    for name in methods:
        correct = sum(r[name] == r["expected"] for r in results)
        acc = correct / len(results)
        latencies = [r[f"{name}_ms"] for r in results if r[f"{name}_ms"]]
        summary[name] = {
            "accuracy": acc,
            "p50_ms": percentile(latencies, 0.5),
            "p90_ms": percentile(latencies, 0.9),
        }
        rows.append([labels[name], f"{correct}/{len(results)}", pct(acc), *latency_cells(latencies)])

        for route in ROUTES:
            gold = [r for r in results if r["expected"] == route]
            predicted = [r for r in results if r[name] == route]
            tp = sum(r[name] == route for r in gold)
            recall = tp / len(gold) if gold else 0.0
            precision = tp / len(predicted) if predicted else 0.0
            summary[name][route] = {"precision": precision, "recall": recall}
            per_class_rows.append([labels[name], route, len(gold), pct(precision), pct(recall)])

    parse_failures = sum(r["supervisor_parse_failed"] for r in results)
    summary["supervisor"]["json_parse_failures"] = parse_failures

    confusion = defaultdict(Counter)
    for r in results:
        confusion[r["expected"]][r["supervisor"]] += 1
    confusion_rows = [[gold] + [confusion[gold][pred] for pred in ROUTES] for gold in ROUTES]

    errors = [r for r in results if r["supervisor"] != r["expected"]]

    report = "\n\n".join([
        "## 路由准确率",
        f"共 {len(results)} 条，类别分布：{dict(Counter(r['expected'] for r in results))}",
        md_table(["路由方式", "正确数", "准确率", "P50(ms)", "P90(ms)"], rows),
        md_table(["路由方式", "类别", "样本数", "精确率", "召回率"], per_class_rows),
        f"意图识别输出无法解析为 JSON（回退为默认路由）：{parse_failures}/{len(results)} 条",
        "当前路由混淆矩阵（行=标注，列=预测）：",
        md_table(["标注 \\ 预测"] + ROUTES, confusion_rows),
        "当前路由错误样例：",
        md_table(["问题", "标注", "预测"], [[r["query"], r["expected"], r["supervisor"]] for r in errors]) if errors else "无",
    ])
    return report, {"summary": summary, "cases": results}


# ─── 检索评测 ───

def rank_of(docs: list[dict], expected: set[str]) -> int | None:
    for rank, doc in enumerate(docs, start=1):
        if doc.get("source") in expected:
            return rank
    return None


async def eval_retrieval(
    llm: ChatOpenAI, memory: LongTermMemory, cases: list[dict], concurrency: int
) -> tuple[str, dict]:
    rag = KnowledgeRAGAgent(llm, memory)
    strategies = ["关键词(二元组)", "向量", "向量+重排", "改写+向量", "改写+向量+重排"]

    async def worker(i: int, case: dict) -> dict:
        query = case["query"]
        expected = set(case["expected_sources"])

        keyword = memory.keyword_search(query, top_k=5)
        vector, vector_ms = await timed(rag.retrieve_documents(query, top_k=5))
        vector_rerank = await rag.rerank_documents(query, vector, top_k=3)
        rewritten, rewrite_ms = await timed(rag.rewrite_query(query))
        rw_vector = await rag.retrieve_documents(rewritten, top_k=5)
        rw_rerank, rerank_ms = await timed(rag.rerank_documents(rewritten, rw_vector, top_k=3))

        ranked = {
            "关键词(二元组)": keyword,
            "向量": vector,
            "向量+重排": vector_rerank,
            "改写+向量": rw_vector,
            "改写+向量+重排": rw_rerank,
        }
        return {
            **case,
            "rewritten": rewritten,
            "ranks": {name: rank_of(docs, expected) for name, docs in ranked.items()},
            "top3": {name: [d.get("source") for d in docs[:3]] for name, docs in ranked.items()},
            "vector_ms": vector_ms,
            "rewrite_ms": rewrite_ms,
            "rerank_ms": rerank_ms,
        }

    results = await run_all(cases, worker, concurrency)

    summary: dict[str, Any] = {}
    rows = []
    for name in strategies:
        ranks = [r["ranks"][name] for r in results]
        hit1 = sum(1 for k in ranks if k is not None and k <= 1) / len(ranks)
        hit3 = sum(1 for k in ranks if k is not None and k <= 3) / len(ranks)
        mrr = sum(1 / k for k in ranks if k is not None and k <= 3) / len(ranks)
        summary[name] = {"recall@1": hit1, "recall@3": hit3, "mrr@3": mrr}
        rows.append([name, pct(hit1), pct(hit3), f"{mrr:.3f}"])

    latency = {
        "向量检索(含 Embedding)": [r["vector_ms"] for r in results],
        "Query 改写": [r["rewrite_ms"] for r in results],
        "LLM 重排": [r["rerank_ms"] for r in results],
    }
    summary["latency_ms"] = {
        k: {"p50": percentile(v, 0.5), "p90": percentile(v, 0.9)} for k, v in latency.items()
    }

    misses = [r for r in results if r["ranks"]["改写+向量+重排"] is None or r["ranks"]["改写+向量+重排"] > 3]

    report = "\n\n".join([
        "## 知识检索",
        f"共 {len(results)} 条口语化问题，知识库 {memory.size} 个片段。"
        "Recall@k = 标注文档出现在前 k 条结果中的比例；MRR@3 按前 3 名计算。",
        md_table(["检索策略", "Recall@1", "Recall@3", "MRR@3"], rows),
        md_table(["环节", "P50(ms)", "P90(ms)"], [[k, *latency_cells(v)] for k, v in latency.items()]),
        "完整链路（改写+向量+重排）未命中样例：",
        md_table(
            ["问题", "改写后", "标注", "实际 Top3"],
            [[r["query"], r["rewritten"], ",".join(r["expected_sources"]), ",".join(r["top3"]["改写+向量+重排"])] for r in misses],
        ) if misses else "无",
    ])
    return report, {"summary": summary, "cases": results}


# ─── 合规评测 ───

async def eval_compliance(llm: ChatOpenAI, cases: list[dict], concurrency: int) -> tuple[str, dict]:
    checker = ComplianceCheckerAgent(llm)
    modes = {"仅规则引擎": checker.rule_check, "仅 LLM": checker.llm_check, "两阶段(规则+LLM)": checker.full_check}

    async def worker(i: int, case: dict) -> dict:
        out = {**case}
        for name, check in modes.items():
            result, ms = await timed(check(case["content"]))
            out[name] = {
                "blocked": not result.passed, "ms": ms,
                "violations": result.violations, "llm_reviewed": result.llm_reviewed,
            }
        return out

    results = await run_all(cases, worker, concurrency)

    summary: dict[str, Any] = {}
    rows = []
    for name in modes:
        tp = sum(r[name]["blocked"] and r["should_block"] for r in results)
        fp = sum(r[name]["blocked"] and not r["should_block"] for r in results)
        fn = sum(not r[name]["blocked"] and r["should_block"] for r in results)
        tn = len(results) - tp - fp - fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        latencies = [r[name]["ms"] for r in results]
        summary[name] = {
            "precision": precision, "recall": recall, "f1": f1,
            "accuracy": (tp + tn) / len(results),
            "p50_ms": percentile(latencies, 0.5), "p90_ms": percentile(latencies, 0.9),
        }
        rows.append([
            name, pct(precision), pct(recall), f"{f1:.3f}", pct((tp + tn) / len(results)),
            *latency_cells(latencies),
        ])

    short_circuited = sum(not r["两阶段(规则+LLM)"]["llm_reviewed"] for r in results)
    summary["两阶段(规则+LLM)"]["short_circuited"] = short_circuited

    categories = sorted({r["category"] for r in results})
    category_rows = []
    for cat in categories:
        subset = [r for r in results if r["category"] == cat]
        row = [cat, len(subset)]
        for name in modes:
            correct = sum(r[name]["blocked"] == r["should_block"] for r in subset)
            row.append(f"{correct}/{len(subset)}")
        category_rows.append(row)

    final = "两阶段(规则+LLM)"
    errors = [r for r in results if r[final]["blocked"] != r["should_block"]]

    report = "\n\n".join([
        "## 合规审查",
        f"共 {len(results)} 条客服回复（应拦截 {sum(r['should_block'] for r in results)} 条）。正例 = 应拦截。",
        md_table(["审查方式", "精确率", "召回率", "F1", "准确率", "P50(ms)", "P90(ms)"], rows),
        f"两阶段审查中由规则引擎直接拦截、未调用 LLM 的：{short_circuited}/{len(results)} 条",
        "按类别的判对数：",
        md_table(["类别", "样本数"] + list(modes), category_rows),
        "两阶段审查判错样例：",
        md_table(
            ["回复内容", "类别", "应拦截", "实际拦截"],
            [[r["content"], r["category"], r["should_block"], r[final]["blocked"]] for r in errors],
        ) if errors else "无",
    ])
    return report, {"summary": summary, "cases": results}


# ─── 入口 ───

async def main() -> None:
    parser = argparse.ArgumentParser(description="智能客服多 Agent 系统离线评测")
    parser.add_argument("--suite", choices=["all", "routing", "retrieval", "compliance"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="每项评测只取前 N 条")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--compliance-set", default="compliance.jsonl", help="合规评测集文件名，留出集为 compliance_holdout.jsonl")
    args = parser.parse_args()

    load_dotenv()
    llm = ChatOpenAI(model=os.getenv("MODEL_NAME", "gpt-4o"), temperature=0, timeout=60, max_retries=3)
    suites = ["routing", "retrieval", "compliance"] if args.suite == "all" else [args.suite]

    sections = []
    details: dict[str, Any] = {}
    started = datetime.now()

    if "routing" in suites:
        print("[1/3] 路由评测")
        report, details["routing"] = await eval_routing(llm, load_jsonl("routing.jsonl", args.limit), args.concurrency)
        sections.append(report)

    if "retrieval" in suites:
        print("[2/3] 检索评测：构建知识库索引")
        memory = LongTermMemory(index_path=str(EVAL_DIR / ".cache" / "faiss_index"))
        memory.load_knowledge_base(KB_DIR)
        report, details["retrieval"] = await eval_retrieval(
            llm, memory, load_jsonl("retrieval.jsonl", args.limit), args.concurrency
        )
        sections.append(report)

    if "compliance" in suites:
        print("[3/3] 合规评测")
        report, details["compliance"] = await eval_compliance(
            llm, load_jsonl(args.compliance_set, args.limit), args.concurrency
        )
        sections.append(report.replace("## 合规审查", f"## 合规审查（{args.compliance_set}）", 1))

    header = "\n".join([
        "# 离线评测报告",
        "",
        f"- 时间：{started:%Y-%m-%d %H:%M}",
        f"- 对话模型：{os.getenv('MODEL_NAME', 'gpt-4o')}",
        f"- Embedding 模型：{os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3')}",
        f"- 耗时：{(datetime.now() - started).total_seconds():.0f} 秒",
    ])
    report = header + "\n\n" + "\n\n".join(sections) + "\n"
    print("\n" + report)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    (RESULT_DIR / f"report_{stamp}.md").write_text(report, encoding="utf-8")
    (RESULT_DIR / f"details_{stamp}.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"已保存：eval/results/report_{stamp}.md")


if __name__ == "__main__":
    asyncio.run(main())
