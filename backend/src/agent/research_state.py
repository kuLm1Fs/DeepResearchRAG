from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    """LangGraph state for Deep Research Supervisor pipeline."""

    query: str                          # 用户原始问题
    task_id: str                        # 任务 ID
    user_id: str                        # 用户标识（PostgreSQL 未就绪时可为 None）
    company_id: str | None              # 公司 ID
    current_step: str                   # 当前步骤: planner/retriever/analyst/checker/writer
    tool_call_count: int                # Tool 调用次数
    max_tool_calls: int                 # 最大调用次数限制（默认 20）

    # Planner 输出
    plan: dict[str, Any] | None         # {goals, audience, output_format, time_window}
    sub_questions: list[str]            # 拆解后的子问题

    # Retriever 输出
    evidence: list[dict[str, Any]]      # 检索到的证据列表

    # Analyst 输出
    analysis: dict[str, Any] | None     # {trends, opportunities, risks}

    # Checker 输出
    check_result: dict[str, Any] | None  # {gaps, conflicts, coverage}
    gaps: list[str]                     # 识别的缺口
    conflicts: list[dict]              # 检测到的冲突

    # Writer 输出
    final_output: dict[str, Any] | None  # {report_md, ppt_outline, slides}
    evidence_trace: list[dict[str, Any]]
    quality_report: dict[str, Any] | None
    execution_log: list[dict[str, Any]]
    memory_snapshot: dict[str, Any] | None

    # 容错
    failed_step: str | None            # 失败步骤
    retry_count: int                   # 重试次数
    error: str | None                  # 错误信息
    on_step: Any                       # Optional async progress callback
