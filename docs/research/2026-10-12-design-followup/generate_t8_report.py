"""Build a read-only process report from saved T8 JSON; no project API or model calls."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
DOCS = HERE.parents[1]
TRIAL = DOCS / "audits/2026-10-11-integration-published-t8"
AUDIT = DOCS / "audits/2026-10-12-t8-fixes-review"


def generate() -> dict:
    sources = {}

    def read(path: Path):
        raw = path.read_bytes()
        sources[str(path.relative_to(DOCS))] = hashlib.sha256(raw).hexdigest()
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        return json.loads(raw)

    preflight = read(TRIAL / "real-trial-preflight.json")
    summary = read(TRIAL / "real-trial-summary.json")
    details = read(TRIAL / "real-project-details-before-restart.json")
    queue = read(TRIAL / "real-queue.json")
    provider = read(TRIAL / "real-provider-events.jsonl")
    initial_failure = read(TRIAL / "real-first-attempt-provider-events.jsonl")
    controlled_failure = read(AUDIT / "logged-out-reader-events.jsonl")
    controlled_result = read(AUDIT / "logged-out-reader-result.json")["data"]
    definition_log = read(AUDIT / "definition-work-log.json")
    start = datetime.fromisoformat(preflight["startingAt"])

    def minute(at):
        return round((datetime.fromisoformat(at) - start).total_seconds() / 60, 2)

    def executions(records):
        completed = [r for r in records if r["event"]["t"] == "done"]
        failures = [r for r in completed if r["event"].get("is_error") or r["event"].get("exit") != 0]
        return {
            "completed": len(completed),
            "execution_failures": len(failures),
            "roles": dict(Counter(r["role"] for r in completed)),
            "usage_including_backend_cache_counts": {
                key: sum(r["event"].get("usage", {}).get(key, 0) for r in completed)
                for key in ("in", "out")
            },
        }

    states = details["nodeState"]
    logs = [(node, event) for node, state in states.items() for event in state["workLog"]]
    verdicts = [(node, event) for node, event in logs if event["kind"] == "verdict"]
    reviews = sorted((event["at"], node) for node, event in logs if event["kind"] == "review-requested")
    final_provisional = sorted(node["id"] for node in details["nodes"]
                               if node["kind"] != "imported_result" and states[node["id"]]["provisional"])
    final_reviews = [(at, node) for at, node in reviews if node in final_provisional]
    queue_counts = Counter(item["kind"] for item in queue["items"])
    unfixed = Counter("Definition" if "definition_id" in item else "statement"
                      for item in queue["items"] if item["kind"] == "unfixed")
    main = executions(provider)
    assert main["completed"] == summary["completedProviderTurns"]
    assert main["usage_including_backend_cache_counts"] == summary["usageIncludingBackendCacheCounts"]
    assert final_provisional == sorted(summary["provisionalProofNodes"])
    assert len(queue["items"]) == summary["queueEntries"]
    assert dict(queue_counts) == summary["queueKinds"]
    assert details["inputSHA256"] == preflight["input"]["sha256"]

    per_node = []
    for node in details["nodes"]:
        node_id = node["id"]
        log = states[node_id]["workLog"]
        if node["kind"] == "imported_result":
            continue
        per_node.append({
            "node": node_id,
            "provider_turns_in_work_log": sum(event["kind"] == "turn" for event in log),
            "verdicts": dict(Counter(event["outcome"] for event in log if event["kind"] == "verdict")),
            "review_requests_minutes": [minute(at) for at, n in reviews if n == node_id],
            "final_provisional": states[node_id]["provisional"],
            "final_conditional_on": states[node_id]["conditionalOn"],
            "parked": any(item["node_id"] == node_id for item in queue["items"] if item["kind"] == "parked"),
        })

    # Only exact repetition is measured. No inferred semantic equivalence or proof correctness.
    explicit_attempts = [(node, event) for node, event in logs if event["kind"] == "attempt"]
    repeated_notes = Counter((node, event.get("note", "")) for node, event in verdicts if event["outcome"] == "failed")
    failed_then_passed = []
    for node, state in states.items():
        events = [event for event in state["workLog"] if event["kind"] == "verdict"]
        for index, event in enumerate(events):
            if event["outcome"] == "failed":
                later = next((v for v in events[index + 1:] if v["outcome"] == "passed"), None)
                if later:
                    failed_then_passed.append({"node": node, "failed_at": event["at"], "passed_at": later["at"]})

    imports = [item for item in queue["items"] if item["kind"] == "imported"]
    unchecked = [{"node": item["node_id"], "marks": len(item["unchecked"])} for item in imports if item["unchecked"]]
    report = {
        "source_sha256": sources,
        "start_europe_zurich": start.astimezone(ZoneInfo("Europe/Zurich")).isoformat(),
        "main_trial": {**main, "elapsed_minutes": summary["elapsedMinutes"], "budget": summary["budget"],
                       "theorem_results": summary["theoremResults"], "verdicts": dict(Counter(e["outcome"] for _, e in verdicts)),
                       "explicit_abandoned_attempts": len(explicit_attempts),
                       "exact_repeated_failed_verdict_notes": sum(count - 1 for count in repeated_notes.values()),
                       "failed_then_passed": failed_then_passed},
        "first_review_request": {"node": reviews[0][1], "minutes": minute(reviews[0][0]),
                                 "final_provisional": reviews[0][1] in final_provisional},
        "earliest_review_request_for_final_provisional_node": {
            "node": final_reviews[0][1], "minutes": minute(final_reviews[0][0])},
        "final_queue": {"entries": len(queue["items"]), "kinds": dict(queue_counts), "unfixed": dict(unfixed)},
        "final_nodes": len(details["nodes"]), "final_provisional_nodes": final_provisional,
        "unchecked_import_marks": unchecked,
        "per_node": per_node,
        "original_failed_reader_separate_from_main_trial": executions(initial_failure),
        "controlled_auth_failure": {**executions(controlled_failure), "reason": controlled_result["reason"],
                                    "reported_status": controlled_result["status"], "budget_spent": controlled_result["budget"]["spent"]},
        "definition_edit_evidence": [e for e in definition_log if e["kind"] == "definition-edited"],
        "unknown": ["human_reading_minutes", "independent_mathematical_attempt_count", "semantic_stagnation_count",
                    "causal_effect_of_route_switching", "independent_mathematical_correctness", "provider_cost"],
    }

    lines = [
        "# T8 离线过程报告", "",
        "生成依据：保存的 JSON/JSONL；未调用模型，未读取或修改项目数据库。输入 SHA-256 见同目录 JSON。",
        f"主试验开始：{report['start_europe_zurich']}（Europe/Zurich）。初次失败与后续受控认证场景分别统计。", "",
        "## 主要发现", "",
        f"- 主试验：{main['completed']} 次 provider 完成，执行失败 {main['execution_failures']}；{summary['elapsedMinutes']:.2f} 分钟。",
        f"- 首次 Review 请求：{reviews[0][1]}，第 {minute(reviews[0][0]):.2f} 分钟；最终不再是 Provisional。",
        f"- 最早请求 Review 且最终仍为 Provisional 的节点：{final_reviews[0][1]}，第 {minute(final_reviews[0][0]):.2f} 分钟。",
        "- 上述时间只表示保存轨迹中的流程交付；本报告未重新验证 snapshot 绑定，也未审定数学正确性。",
        f"- 最终 {len(details['nodes'])} 个节点、{len(final_provisional)} 个 Provisional proof nodes；主定理 stuck，3 个 Parked；未发生人工 Acceptance 或 Reference review。",
        f"- 显式 abandoned attempt {len(explicit_attempts)} 条；failed Verifier verdict 1 条，随后出现修正与 passed；这些不能拼成独立数学尝试总数。",
        "- 阅读时间未知。队列规模可以诊断材料组成，不能证明阅读耗时或证据表的收益。", "",
        "## 队列组成", "", "| 项目 | 条数 |", "|---|---:|",
    ]
    lines += [f"| {kind} | {count} |" for kind, count in queue_counts.items()]
    lines += [
        f"| 合计 | {len(queue['items'])} |", "",
        f"unfixed 拆分为 {unfixed['statement']} 个 statement 和 {unfixed['Definition']} 个 Definition。",
        "同一节点可能同时涉及文本确认、证明审阅和问题。68 项不是 68 个互不重叠的数学判断。", "",
        "优先降低每项寻找来源和理解修改的成本。来源字段覆盖只作诊断；主要收益指标应为人工阅读/核对时间与遗漏发现。", "",
        "## 执行失败与数学停滞分开", "",
        "| 场景 | 完成启动 | 执行失败 | input/output token | 数学尝试 |", "|---|---:|---:|---|---|",
        f"| 主试验 | {main['completed']} | {main['execution_failures']} | {main['usage_including_backend_cache_counts']['in']:,} / {main['usage_including_backend_cache_counts']['out']:,} | 总数未知 |",
        "| 原始首个 Reader | 1 | 1 | 0 / 0 | 认证失败，不作为数学尝试 |",
        "| 受控未登录 Reader | 1 | 1 | 0 / 0 | 认证失败，不作为数学尝试 |", "",
        f"受控结果：`{controlled_result['reason']}`；API status 仍为 `{controlled_result['status']}`，budget spent 为 {controlled_result['budget']['spent']}。",
        "分类依据是保存的 nonzero exit/is_error 和认证复现，不是零 token 或 subtype success。一次实际启动仍消耗执行预算，本报告没有退款、重试或状态机改动。",
        "主试验 token 的 input 包含 backend cache creation/read 计数；不能据此推定账单金额。", "",
        "## 节点轨迹", "", "| 节点 | 日志中的 provider turns | Review 时间/分钟 | Verifier pass/fail | 最终 Provisional | Parked |", "|---|---:|---|---|---|---|",
    ]
    for node in per_node:
        counts = node["verdicts"]
        times = ", ".join(f"{t:.2f}" for t in node["review_requests_minutes"]) or "—"
        lines.append(f"| {node['node']} | {node['provider_turns_in_work_log']} | {times} | {counts.get('passed', 0)}/{counts.get('failed', 0)} | {'是' if node['final_provisional'] else '否'} | {'是' if node['parked'] else '否'} |")
    lines += [
        "", "Reader 是项目级 turn，没有伪造归属到某个节点。节点 work log 合计 39 turns，加 Reader 1 turn 为主试验 40。",
        "hilbert-space-decomposition 有较早的 passed verdict/Review 请求，但结构改变后最终不是 Provisional。它说明早期交付与最终可用材料应分别报告。", "",
        "## 来源与修改的可见性", "",
        f"10 个 imports 全部未 Reference review；其中 {len(unchecked)} 个带显式 unchecked-source marks。没有 mark 的其余项不自动算已核对原文。",
        "受控 Definition-edit 记录已含 definition_id=D、by=reader-1、role=decomposer、reason=n = 1 is degenerate 和旧→新文本。第一增量是让界面显示现有信息。", "",
        "## 本报告不能确定", "",
        "- 人工阅读与修改时间、证据表是否降低核对成本。",
        "- 语义重复 objection 的次数、独立数学尝试总数，以及因果意义上的路线停滞。",
        "- 较早自动换路线能否解决三个 Parked 问题。保存的 objections 是模型报告，未经本次独立数学审定。",
        "- 提示词约束在真实 agent 中的有效率。测试只能检查接线与既有流程。", "",
        "## 据此作出的下一步判断", "",
        "先复用 #197 的错误原因/Definition 展示修复，落实 Decomposer 路线约束和 Verifier 清单。证据表与提前换路线机制保持待定。",
        "若要验证证据表，应对少量同一冻结材料做人工定时核对，记录漏项与阅读时间；不以新增字段数作为成功标准。", "",
        "再生成：`python docs/research/2026-10-12-design-followup/generate_t8_report.py`。",
    ]
    (HERE / "t8-process-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (HERE / "t8-process-report.md").write_text("\n".join(lines) + "\n")
    return report


if __name__ == "__main__":
    result = generate()
    print(f"T8 report: {result['main_trial']['completed']} provider turns, {result['final_queue']['entries']} queue entries; no model calls")
