"""Thin orchestration loop for the modular exploration kernel."""

from __future__ import annotations

from copy import deepcopy
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
import time
import json
import hashlib

from .actions import action_dict, is_android, to_primitive, validate_for_platform
from .agent import (
    CodexExplorerAgent,
    OpenAIAPIExplorerAgent,
    QwenExplorerAgent,
)
from .api_config import ExploreAPIConfig
from .anchors import (
    capture_click_anchor,
    compare_action_effects,
    relocate_click_anchor,
    visible_change_ratio,
)
from .artifacts import ArtifactStore
from .bundle import compile_modular_bundle
from .contracts import (ActionRequest, AgentTurn, PageReport, PreviousActionReport,
                        ReportCorrections, ReportCorrectionExhausted)
from .inventory import apply_page_report
from .ledger import ExplorationLedger
from .location import bind_screen, validate_state_composition
from .models import (
    ActionAttempt,
    CanonicalOperation,
    Element,
    OPEN_OPERATION_STATES,
    OPEN_TASK_STATES,
    Operation,
    Task,
    Transition,
)
from .region_review import (
    pending_region_reviews,
    review_page_report_element_candidates,
    review_region_identity,
)
from .regions import merge_operation_identity
from .resume import prepare_resume_region_rediscovery
from .scope import ScopeGuard
from .settlement import (
    SettlementContractError,
    resolve_action_operation,
    settle_completed_actions,
)
from .status import (
    build_agent_context,
    current_operation_binding,
    current_page_record,
)
from .tasks import (
    apply_representative_probe,
    deferred_inventory_reports,
    TaskScheduler,
    logical_task_count,
    task_source_states,
)
from .region_routes import (
    plan_region_route,
    refresh_transition_region_effects,
    record_region_effects,
)


MAX_OPERATION_ATTEMPTS = 12
MAX_SURVEY_ATTEMPTS = 12
MAX_CONSECUTIVE_ACTION_REJECTIONS = 4
MAX_EXTERNAL_RECOVERY_ATTEMPTS = 3
MAX_NO_EFFECT_RECOVERY_ATTEMPTS = 2
MAX_NO_EFFECT_OPERATION_ATTEMPTS = 2
UNCHANGED_FRAME_RATIO = 0.0001
DETOUR_POINT_REPEAT_RADIUS_1000 = 25.0


class ContextLookupExhausted(ValueError):
    """A repeated/budgeted lookup, distinct from an invalid query reference."""


@dataclass(frozen=True)
class ExplorationResult:
    status: str
    stop_reason: str
    actions_used: int
    model_turns: int
    output_root: str
    gaps: Sequence[str]


class ExplorationRuntime:
    """Own only episode boundaries; semantics stay in Agent reports."""

    def __init__(
        self,
        *,
        env: Any,
        app_name: str,
        platform: str,
        output_root: str,
        agent: QwenExplorerAgent,
        max_actions: int,
        desktop_window_owner: Any = None,
        relaunch_fn: Any = None,
        run_checkpoint: Any = None,
        package_versions: Optional[Mapping[str, str]] = None,
        seed_plan_digest: str = "",
        save_environment: Any = None,
        delete_environment: Any = None,
        exploration_goal: str = "",
        execution_scope: str = "",
        defer_partition_review: bool = False,
    ) -> None:
        self.env = env
        self.app_name = app_name
        self.platform = platform
        self.output_root = output_root
        self.exploration_goal = str(exploration_goal or "")
        self.execution_scope = str(execution_scope or exploration_goal or "")
        self.defer_partition_review = bool(defer_partition_review)
        self.agent = agent
        self.max_actions = int(max_actions)
        self.max_turns = max(12, self.max_actions * 4)
        self.ledger = ExplorationLedger()
        self.scheduler = TaskScheduler()
        self.run_checkpoint = run_checkpoint
        self.package_versions = dict(package_versions or {})
        self.seed_plan_digest = str(seed_plan_digest or "")
        self.save_environment = save_environment
        self.delete_environment = delete_environment
        self.artifacts = ArtifactStore(
            output_root,
            checkpoint_callback=(
                self._checkpoint_run_environment
                if run_checkpoint is not None else None),
        )
        self.scope = ScopeGuard(
            env=env,
            app_name=app_name,
            platform=platform,
            desktop_window_owner=desktop_window_owner,
            relaunch_fn=relaunch_fn,
        )
        self.pending_attempt_id = ""
        self.pending_before = b""
        self.pending_action_error = ""
        self.restored_delivery = None
        self.context_lookup_scope = ""
        self.context_lookup_query = ""
        self.context_lookup_queries: list[str] = []
        self.correction = ""
        self.actions_used = 0
        self.model_turns = 0
        self.rejection_task_id = ""
        self.rejection_issue = ""
        self.rejection_streak = 0
        self.last_context_task_id: Optional[str] = None
        self.confirmed_state_id = ""
        self.confirmed_screenshot = b""
        self.external_recovery_attempts = 0
        self.model_scope_conflicts = 0
        self.restart_recovery_task_id = ""
        self.restarted_recovery_task_ids: set[str] = set()
        self.resume_error = ""
        self.resume_region_rediscovery_required = False
        self.report_corrections = ReportCorrections()
        self.blocked_report_state = ""
        self.report_correction_stop_reason = ""
        self.pending_report_correction: Dict[str, Any] = {}
        self.retained_effect_inventory: Optional[tuple[str, bytes, AgentTurn]] = None
        self.retained_partition_screen = None
        self.report_repair_base = None
        self.known_state_review_key = ()
        self.partition_review_cache = {}
        self.taskless_recovery_error = ""

    def _checkpoint_run_environment(self, ledger: ExplorationLedger) -> None:
        """Persist only a settled ledger beside its exact run-owned AVD state."""
        if (
            self.run_checkpoint is None
            or self.save_environment is None
            or self.delete_environment is None
        ):
            return
        self.run_checkpoint.save(
            ledger.snapshot(),
            app_id=self.app_name,
            package_versions=self.package_versions,
            seed_plan_digest=self.seed_plan_digest,
            save_environment=self.save_environment,
            delete_environment=self.delete_environment,
        )

    def restore(self, ledger_path: str) -> bool:
        """Load a modular checkpoint for fresh Region discovery."""
        self.resume_error = ""
        path = Path(ledger_path).resolve()
        expected = (self.artifacts.root / "exploration_ledger.json").resolve()
        if path != expected:
            self.resume_error = "resume ledger must be in the active output root"
            return False
        try:
            candidate = ExplorationLedger.load(path)
        except (OSError, TypeError, ValueError) as exc:
            self.resume_error = f"resume ledger unavailable: {type(exc).__name__}"
            return False
        candidate.coalesce_operation_tasks()
        from .resume import resumable_delivery
        delivery = resumable_delivery(candidate, self.artifacts)
        prepare_resume_region_rediscovery(candidate, retained_attempt_id=delivery[0] if delivery else '')
        candidate.event(
            "resume_started",
            ledger_path=str(path),
            page_id="",
            state_id="",
            rediscover_regions=True,
            reason="rediscover visible Regions from the fresh screenshot",
        )
        self.ledger = candidate
        self.actions_used = len(candidate.attempts)
        self.pending_attempt_id = ""
        self.pending_before = b""
        self.restored_delivery = delivery
        if delivery:
            self.pending_attempt_id, self.pending_before, _ = delivery
            attempt = candidate.attempts[self.pending_attempt_id]
            candidate.current_state_id = attempt.source_state_id
            candidate.current_page_id = candidate.states[attempt.source_state_id].page_id
            candidate.event('resume_delivery_evidence_retained', attempt_id=attempt.attempt_id,
                reason='Review captured delivery frames only; fresh location required before any new action')
        self.resume_region_rediscovery_required = not bool(delivery)
        self.scheduler.work_region_id = ''
        self.scheduler.closed_region_signatures = {}
        self.scheduler.last_region_exit = {}
        self.retained_effect_inventory = None
        self.retained_partition_screen = None
        self.report_repair_base = None
        self.partition_review_cache = {}
        self.confirmed_state_id = ""
        self.confirmed_screenshot = b""
        self.artifacts.archive_completion()
        self.artifacts.checkpoint(self.ledger)
        return True

    def _context(self, task: Optional[Task], system_scope: str) -> Dict[str, Any]:
        task_id = task.task_id if task is not None else ""
        last_task_id = getattr(self, "last_context_task_id", None)
        binding = current_operation_binding(self.ledger, task.operation_id) if task and task.operation_id else None
        binding_id = binding.operation_id if binding is not None else ""
        last_binding_id = getattr(self, "last_context_operation_id", None)
        binding_changed = bool(last_binding_id and binding_id and last_binding_id != binding_id)
        if (last_task_id not in {None, ""} and (task_id != last_task_id or binding_changed)
                and not self.pending_attempt_id
                and not self._report_budget().count):
            self.correction = ""
            self._clear_action_rejections()
            if binding_changed and task is not None:
                task.strategy = ""
        self.last_context_task_id = task_id
        self.last_context_operation_id = binding_id
        context = build_agent_context(
            self.ledger, task, system_scope,
            app_name=self.app_name,
            platform=self.platform,
            pending_attempt_id=self.pending_attempt_id,
            correction=(str({key: self.pending_report_correction[key]
                             for key in ('field_path', 'received', 'unresolved_inventory')
                             if key in self.pending_report_correction})
                        if (getattr(self, 'current_submission', {}).get('phase') == 'inventory_edits'
                            and self.pending_report_correction)
                        else self.correction),
            rejection_count=(
                self.rejection_streak
                if task is not None and task.task_id == self.rejection_task_id
                else 0),
            rejection_limit=MAX_CONSECUTIVE_ACTION_REJECTIONS,
            pending_report_correction=getattr(self, "pending_report_correction", {}),
            rediscovering=getattr(self, "resume_region_rediscovery_required", False),
            exploration_goal=getattr(self, "exploration_goal", ""),
            submission=getattr(self, "current_submission", None),
            context_query=(getattr(self, "context_lookup_query", "")
                           if getattr(self, "context_lookup_scope", "")
                           == self._context_lookup_scope() else ""),
        )
        if getattr(self, 'restored_delivery', None):
            context['恢复结算证据'] = '当前双图是原投递同步保存的前后帧，只核验原动作；不是现在的现场。action=null。结算后框架重新观察现场，不沿用该位置投递。'
        from .region_work import region_coverage, environment_view
        scheduler = getattr(self, 'scheduler', None)
        region_ref = getattr(scheduler, 'work_region_id', '')
        if not region_ref and task is not None and task.operation_id in self.ledger.operations:
            region_ref = self.ledger.operations[task.operation_id].region_id
        declaration = getattr(scheduler, 'region_declarations', {}).get(region_ref)
        if region_ref:
            direct_coverage = region_coverage(self.ledger, region_ref, declaration)
            context['工作区块'] = {'region_ref': region_ref,
                'coverage': {key: value for key, value in direct_coverage.items() if key != 'operations'},
                'last_exit': getattr(scheduler, 'last_region_exit', {}),
                'instruction': '工作Region的直属一层优先；子Region待办独立保留，前景变化不是工作范围自动切换。'
                               '已登记不等于交互验证，当前无待办不等于完成；不要为补覆盖无条件执行受限或缺条件操作。'
                               '临时进入子前景只是验证父操作，结算后按当前图安全返回工作Region继续；无安全返回则保留阻塞。'
                               '关闭/取消通常在其他适用直属操作之后，安全需要可提前退出并说明。'}
            context['任务相对环境'] = environment_view(self.ledger, region_ref, task,
                scale=getattr(self, 'context_view_scale', 'region'), declaration=declaration,
                pending=bool(self.pending_attempt_id))
        context['推进阶段'] = (context['本轮提交合同'] if context['本轮提交合同']['phase'] == 'inventory_edits'
                            else self._progress_phase(task))
        if getattr(self, 'execution_scope', ''):
            context['探索范围'] = {'goal': self.execution_scope, 'source': 'runtime configuration'}
        if getattr(self, "defer_partition_review", False):
            context["分区复核策略"] = (
                "本轮延后整页分区预审，分区质量保留待复核缺口，不代表图完整。"
                "区块边界不明确时先归当前图确实存在的容器，说明未知，后续可用region_refinement细化。"
                "可先提交不完整清单，下一轮使用当前已登记owner继续；不要为完美分区反复重报整页。"
                "当前控件必须真实可见且可定位；不能复制背景或历史控件，不因名称相同共享身份。"
                "动作仍须原引用、可用性及前后图结算；有不确定身份时保留不同对象。")
        return context

    @staticmethod
    def _report_error_fields(error: Exception) -> Dict[str, str]:
        if isinstance(error, SettlementContractError):
            return {
                "error_code": error.code,
                "field_path": error.field_path,
                "expected": error.expected,
                "received": error.received,
            }
        return {
            "error_code": "UNMAPPED_REPORT_CONTRACT_ERROR",
            "field_path": "unclassified",
            "expected": "框架未能定位具体子字段；请保留真实动作事实，不能根据未分类异常猜测控件身份或成功结果",
            "received": str(error)[:300],
        }

    def _report_budget(self) -> ReportCorrections:
        if not hasattr(self, "report_corrections"):
            self.report_corrections = ReportCorrections()
        return self.report_corrections

    def _remember_report_repair(self, screen, report, previous, screenshot):
        if screen is None or not bind_screen(self.ledger, screen, screenshot_ref="").ok:
            return
        self.retained_partition_screen = (self.pending_attempt_id, screenshot, screen)
        self.report_repair_base = None
        self.report_edit_application = '位置/回执/清单仅暂存，尚未发布；没有本轮编辑应用事实'
        if isinstance(report, dict) and isinstance(report.get("regions"), list):
            self.report_repair_base = (self.pending_attempt_id, screenshot, deepcopy(report), previous)

    def _materialize_report_edits(self, turn, screenshot, frame_ref, *, edit_trace=None):
        from .contracts import _parse_page_report
        from .report_edits import apply_report_edits
        base = getattr(self, "report_repair_base", None)
        screen = self._partition_screen_for_frame(screenshot)
        if base is None or screen is None or base[:2] != (self.pending_attempt_id, screenshot):
            raise ValueError("page_report_edits requires the same frame/attempt repair card; submit a fresh complete report")
        if bool(self.pending_attempt_id) != (base[3] is not None):
            raise ValueError("page_report_edits cannot inherit a missing or unrelated action receipt")
        if base[3] is not None:
            if base[3].attempt_ref != self.pending_attempt_id:
                raise ValueError("page_report_edits cached receipt belongs to another attempt; submit full corrected receipt")
            indexed = [e.get("report_index") for e in (base[3].region_effects or [])
                       if isinstance(e.get("report_index"), int)]
            for edit in turn.page_report_edits:
                parts = str(edit.get("path", "")).split("/")
                if len(parts) == 3 and parts[1] == "regions" and parts[2].isdigit():
                    index = int(parts[2])
                    if ((edit.get("op") in {"add", "remove"} and any(i >= index for i in indexed))
                            or (edit.get("op") == "replace" and index in indexed)):
                        raise ValueError("page_report_edits会改变回执引用的Region索引；保持这些行，或先退出编辑阶段再同步重判清单与回执")
        edited = apply_report_edits(base[2], turn.page_report_edits, trace=edit_trace)
        # Keep the edited proposal even if a field still fails parsing, so the
        # next correction's indices refer to the candidate actually inspected.
        self.report_repair_base = (base[0], base[1], edited, base[3])
        self.ledger.event("page_report_edits_applied", screenshot_ref=frame_ref,
            edits=deepcopy(turn.page_report_edits), published=False)
        self.report_edit_application = '编辑已应用到暂存候选，尚未发布；以当前候选索引继续核验'
        try:
            report = _parse_page_report(edited)
        except (TypeError, ValueError) as error:
            error.edit_application = self.report_edit_application
            raise
        return replace(turn, screen=screen, previous_action=base[3], page_report=report, page_report_edits=None)

    def _partition_screen_for_frame(self, screenshot: bytes):
        retained = getattr(self, "retained_partition_screen", None)
        if retained is None:
            return None
        attempt_id, frame, screen = retained
        if attempt_id != self.pending_attempt_id or frame != screenshot:
            self.retained_partition_screen = None
            self.report_repair_base = None
            return None
        return screen

    def _effect_inventory_for_frame(self, screenshot: bytes) -> Optional[AgentTurn]:
        retained = getattr(self, "retained_effect_inventory", None)
        if retained is None:
            return None
        attempt_id, frame, turn = retained
        if (attempt_id != self.pending_attempt_id or frame != screenshot
                or self.pending_report_correction.get("field_path") != "previous_action.region_effects"):
            self.retained_effect_inventory = None
            return None
        return turn

    def _flush_report_corrections(self) -> None:
        budget = self._report_budget()
        for event in budget.events:
            self.ledger.event("report_correction", **event)
        budget.events.clear()

    def _accept_report_corrections(self, *, interface_changed: bool = False) -> None:
        self.retained_partition_screen = None
        self.report_repair_base = None
        budget = self._report_budget()
        self._flush_report_corrections()
        deferred = deferred_inventory_reports(self.ledger)
        if self.blocked_report_state in deferred:
            if not interface_changed:
                return
            self.ledger.event("report_correction_context_changed",
                              deferred_state_id=self.blocked_report_state,
                              current_state_id=self.ledger.current_state_id)
            budget.reset()
            self.blocked_report_state = ""
            return
        if budget.count and (budget.count < budget.limit or interface_changed):
            self.ledger.event("report_correction_resolved", rejected_rounds=budget.count,
                              resolved=True)
            budget.reset()
            self.blocked_report_state = ""

    def _end_report_corrections(self, turn: AgentTurn, task: Optional[Task], error: Exception,
                                *, frame_ref: str) -> None:
        budget = self._report_budget()
        self._flush_report_corrections()
        current = self.ledger.current_state_id
        safe_position = bool(current and turn.screen is not None
                             and turn.screen.identity == "known"
                             and turn.screen.state_ref == current
                             and not getattr(self, "resume_region_rediscovery_required", False))
        reason = f"报告与身份审核共用的{budget.limit}轮预算已耗尽：{error}"
        held = self.ledger.tasks.get(task.task_id) if task is not None else None
        if held is not None and held.status in {"pending", "active", "deferred"}:
            held.status = "failed"
            held.reason = reason
            if self.ledger.current_task_id == held.task_id:
                self.ledger.current_task_id = ""
        self.blocked_report_state = current
        self.pending_report_correction = {}
        self.retained_effect_inventory = None
        self.retained_partition_screen = None
        self.report_repair_base = None
        self.ledger.event("report_correction_exhausted", state_ref=current,
                          task_ref=held.task_id if held else "", count=budget.count,
                          limit=budget.limit, reason=reason, screenshot_ref=frame_ref,
                          candidate_report=asdict(turn.page_report) if turn.page_report else None,
                          proposed_screen=asdict(turn.screen) if turn.screen else None)
        self.correction = (reason + "。冲突清单未提交；不要重提本页同一审核，"
                           "可沿已有绑定导航到其他内容；无安全路线则保留partial缺口。")
        self.last_context_task_id = None
        if not safe_position:
            self.report_correction_stop_reason = "report_correction_exhausted"

    def _force_release_pending_report(
        self,
        *,
        task: Optional[Task],
        screenshot: bytes,
        frame_ref: str,
        card: Dict[str, Any],
    ) -> None:
        attempt_id = self.pending_attempt_id
        attempt = self.ledger.attempts[attempt_id]
        actual_operation_ref = str(
            attempt.action.get("operation_ref") or "")
        reason = (
            f"同一 pending 报告连续 {card['correction_count']} 次未通过"
            f"合同（{card['error_code']} / {card['field_path']}）；"
            "框架丢弃无法绑定的声明，保留 before/action/after 并停止重复动作。"
        )
        safe_report = PreviousActionReport(
            attempt_ref=attempt_id,
            outcome="uncertain",
            task_result="failed",
            visible_result=reason,
            reason=reason,
        )
        safe_turn = AgentTurn(
            app_scope="target_app",
            strategy="合同纠正达到上限，保守释放 pending。",
            screen=None,
            previous_action=safe_report,
            page_report=None,
            action=None,
            current_task_result="",
            reason=reason,
        )
        self._settle_pending(
            safe_turn,
            screenshot=screenshot,
            frame_ref=frame_ref,
        )
        operation = self.ledger.operations.get(actual_operation_ref)
        operation_task = (
            self.ledger.operation_task(actual_operation_ref)
            if operation is not None else None
        )
        if operation_task is not None and operation_task.status in {
                "pending", "active", "deferred"}:
            self.scheduler.settle(
                self.ledger, operation_task,
                result="failed", reason=reason)
        elif operation is not None and operation.status in {
                "pending", "active", "deferred"}:
            operation.status = "failed"
            operation.reason = reason
            operation.result = reason
        elif (operation is None
              and task is not None
              and task.status in {"pending", "active", "deferred"}):
            self.scheduler.settle(
                self.ledger, task, result="failed", reason=reason)
        self.ledger.event(
            "pending_report_correction_budget_exhausted",
            attempt_id=attempt_id,
            actual_operation_ref=actual_operation_ref,
            error_code=card["error_code"],
            field_path=card["field_path"],
            correction_count=card["correction_count"],
            reason=reason,
        )
        self.correction = (
            "上一 pending 报告纠正达到上限，框架已保守保存证据并释放；"
            "不得重复该 GUI 动作。请根据 fresh screenshot 继续其他任务。"
        )

    def _reject_observation_report(
        self,
        baseline: ExplorationLedger,
        turn: AgentTurn,
        task: Optional[Task],
        error: Exception,
        *,
        screenshot: bytes,
        frame_ref: str,
    ) -> None:
        """Discard staged graph facts while retaining the real action evidence."""
        self.ledger = baseline
        if getattr(error, "code", "") in {"PARTITION_VISUAL_UNCONFIRMED", "PAGE_REPORT_STRUCTURE"} and turn.page_report is not None:
            self._remember_report_repair(turn.screen, asdict(turn.page_report), turn.previous_action, screenshot)
        if self._settle_with_deferred_inventory(
                baseline, turn, error, screenshot=screenshot, frame_ref=frame_ref):
            return
        budget = self._report_budget()
        budget.required_report = budget.required_report or bool(
            self._report_error_fields(error)["field_path"].startswith("page_report"))
        if self.pending_attempt_id:
            attempt = self.ledger.attempts[self.pending_attempt_id]
            attempt.after_ref = self.artifacts.save_attempt_after(
                attempt.attempt_id, screenshot)
            self._handle_pending_report_rejection(
                turn=turn, task=task, error=error,
                screenshot=screenshot, frame_ref=frame_ref,
            )
        else:
            retry = budget.reject(error, "main_agent")
            self._flush_report_corrections()
            self.correction = f"本轮报告未接受，未执行新动作。纠正 {budget.count}/{budget.limit}：{error}"
            # The rejected observation belongs to the page, even if scheduling changes.
            self.last_context_task_id = None
            self.ledger.event(
                "page_report_rejected", reason=self.correction,
                screenshot_ref=frame_ref,
            )
            if not retry:
                self._end_report_corrections(turn, task, error, frame_ref=frame_ref)

    def _settle_with_deferred_inventory(
        self, baseline: ExplorationLedger, turn: AgentTurn, error: Exception,
        *, screenshot: bytes, frame_ref: str,
    ) -> bool:
        """Commit a valid known-state action without publishing a rejected inventory."""
        if (not self.pending_attempt_id or turn.previous_action is None
                or turn.page_report is None or turn.screen is None
                or turn.app_scope != "target_app" or turn.screen.identity != "known"
                or not self._report_error_fields(error)["field_path"].startswith("page_report")
                or self.pending_action_error or self.resume_region_rediscovery_required):
            return False
        target = baseline.states.get(turn.screen.state_ref)
        attempt = baseline.attempts.get(self.pending_attempt_id)
        if (target is None or not target.region_occurrence_ids or attempt is None
                or attempt.action.get("operation_ref") not in baseline.operations
                or turn.previous_action.attempt_ref != attempt.attempt_id):
            return False
        if getattr(error, 'code', '') in {'PARTITION_VISUAL_UNCONFIRMED', 'PARTITION_RESULT_DEPENDENCY'}:
            # A foreground/partition dispute is not an independent missing item.
            return False
        if callable(getattr(self.agent, 'review_known_state', None)):
            import hashlib
            proof = getattr(self, 'known_state_review_key', ())
            if len(proof) < 3 or proof[0] != target.state_id or proof[2] != hashlib.sha256(screenshot).hexdigest():
                return False  # never bypass current visual admission via a bad inventory
        known_regions = {item.region_id for item in baseline.state_occurrences(target.state_id)}
        if any(item.region_ref not in known_regions for item in turn.page_report.regions):
            return False
        known_effects = []
        for item in turn.previous_action.region_effects or ():
            effect = dict(item)
            index = effect.get("report_index")
            if index is not None:
                ref = effect.get("region_ref")
                if (ref not in baseline.regions or not 0 <= index < len(turn.page_report.regions)
                        or turn.page_report.regions[index].region_ref != ref):
                    return False
                effect["report_index"] = None
            known_effects.append(effect)
        location = bind_screen(baseline, turn.screen, screenshot_ref=frame_ref)
        if not location.ok or location.created_state:
            return False
        self.ledger = location.ledger
        attempt_id = self.pending_attempt_id
        try:
            self._settle_pending(replace(turn, page_report=None, action=None),
                                 screenshot=screenshot, frame_ref=frame_ref, finalize=False)
            if self.ledger.attempts[attempt_id].outcome != "success":
                self.ledger = baseline
                return False
            if turn.previous_action.region_effects is not None:
                record_region_effects(self.ledger, attempt_id, known_effects, ())
        except (TypeError, ValueError):
            self.ledger = baseline
            return False
        self._finish_pending_settlement()
        self.ledger.event("inventory_report_deferred", state_id=location.state_id,
                          attempt_id=attempt_id, reason=str(error),
                          screenshot_ref=frame_ref, candidate_report=asdict(turn.page_report))
        survey = self.ledger.survey_task(location.state_id)
        if survey is not None and survey.status in {"pending", "active"}:
            survey.status = "deferred"
            survey.reason = "动作已独立结算；未接受清单保留待补，先探索其他可用内容。"
            if self.ledger.current_task_id == survey.task_id:
                self.ledger.current_task_id = ""
        budget = self._report_budget()
        budget.reject(error, "main_agent")
        budget.required_report = False
        self._flush_report_corrections()
        self.blocked_report_state = location.state_id
        self.correction = ""
        self.last_context_task_id = None
        self.confirmed_state_id = location.state_id
        self.confirmed_screenshot = screenshot
        self.artifacts.checkpoint(self.ledger)
        return True

    def _handle_pending_report_rejection(
        self,
        *,
        turn: AgentTurn,
        task: Optional[Task],
        error: Exception,
        screenshot: bytes,
        frame_ref: str,
    ) -> bool:
        attempt_id = self.pending_attempt_id
        budget = self._report_budget()
        retry = budget.reject(error, "main_agent")
        count = budget.count
        self._flush_report_corrections()
        fields = self._report_error_fields(error)
        inventory_correction = fields["field_path"].startswith("page_report")
        correction_target = "page_report" if inventory_correction else fields["field_path"]
        if fields["field_path"].startswith("screen"):
            correction_target = "screen"
        card: Dict[str, Any] = {
            "pending_attempt_ref": attempt_id,
            **fields,
            "accepted_facts": [
                f"attempt_ref={attempt_id}",
                "GUI action already executed",
                "the real action and before screenshot are retained; after is the current observation",
            ],
            "required_change": (
                f"修正 {fields['field_path']}；若分区或状态相关，同步修正 screen/page_report/previous_action.region_effects"
                + (f"\n本轮具体反馈（仅用于修正当前报告，不改变动作与安全合同）：{error}"
                   if str(error).strip() else "")),
            "forbidden": [
                "action must be null",
                "do not repeat the GUI action",
            ],
            "correction_count": count,
            "correction_limit": budget.limit,
        }
        base = getattr(self, 'report_repair_base', None)
        if base is not None and base[:2] == (attempt_id, screenshot):
            import hashlib
            binding = (attempt_id, hashlib.sha256(screenshot).hexdigest(),
                       hashlib.sha256(json.dumps(base[2], sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            previous = self.pending_report_correction.get('unresolved_inventory')
            if inventory_correction:
                card['unresolved_inventory'] = {'binding': binding, 'required_change': str(error)}
            elif previous and tuple(previous['binding']) == binding:
                card['unresolved_inventory'] = previous
                card['inventory_note'] = '格式/回执约束仍须修正；同一未修改候选的以下清单问题也尚未解决，不要重复追加已有条目。'
        self.pending_report_correction = card
        self.ledger.event(
            "completed_action_report_rejected",
            attempt_id=attempt_id,
            error_code=fields["error_code"],
            field_path=fields["field_path"],
            expected=fields["expected"],
            received=fields["received"],
            correction_count=count,
            correction_limit=budget.limit,
            reason=str(error)[:500],
        )
        if retry:
            self.correction = (
                f"待结算报告字段 {fields['field_path']} 未通过："
                f"期望 {fields['expected']}，收到 {fields['received']}。"
                f"修正 {correction_target} 并同步相关分区引用；action 必须为 null，真实动作与 attempt_ref 不得改写。"
            )
            return False
        self._force_release_pending_report(
            task=task,
            screenshot=screenshot,
            frame_ref=frame_ref,
            card=card,
        )
        self._end_report_corrections(turn, task, error, frame_ref=frame_ref)
        return True

    def _handle_agent_decide_failure(
        self,
        *,
        task: Optional[Task],
        error: Exception,
        screenshot: bytes,
        frame_ref: str,
    ) -> bool:
        self.report_edit_application = getattr(error, 'edit_application', '整批编辑未应用，缓存候选未变化')
        screen_candidate = getattr(error, "screen_candidate", None)
        if screen_candidate is not None:
            self._remember_report_repair(screen_candidate, getattr(error, "page_report_candidate", None),
                getattr(error, "previous_action_candidate", None), screenshot)
        failed_turn = AgentTurn(
            app_scope="target_app",
            strategy="模型回复未通过 schema。",
            screen=None,
            previous_action=None,
            page_report=None,
            action=None,
            current_task_result="",
            reason=str(error)[:500],
        )
        if not self.pending_attempt_id:
            budget = self._report_budget()
            retry = budget.reject(error, "main_agent")
            self._flush_report_corrections()
            self.correction = f"主Agent格式纠正 {budget.count}/{budget.limit}：{error}"
            self.last_context_task_id = None
            if not retry:
                self._end_report_corrections(failed_turn, task, error, frame_ref=frame_ref)
            return True
        self._handle_pending_report_rejection(
            turn=failed_turn,
            task=task,
            error=error,
            screenshot=screenshot,
            frame_ref=frame_ref,
        )
        return True

    def _settle_pending(
        self,
        turn: AgentTurn,
        *,
        screenshot: bytes,
        frame_ref: str,
        finalize: bool = True,
    ) -> None:
        if not self.pending_attempt_id or turn.previous_action is None:
            return
        attempt = self.ledger.attempts[self.pending_attempt_id]
        report = turn.previous_action
        if attempt.outcome != 'pending':
            raise ValueError('已处理的历史Attempt不能重新结算。')
        unbound_action = not str(
            attempt.action.get("operation_ref") or "")
        if (unbound_action
                and any(
                    item.completed
                    for item in (
                        tuple(report.element_actions)
                        + tuple(report.region_actions)
                    ))):
            report = replace(
                report,
                element_actions=(),
                region_actions=(),
                parameter_info=None,
            )
            self.ledger.event(
                "unbound_action_completed_owners_ignored",
                attempt_id=attempt.attempt_id,
                purpose=attempt.purpose,
                reason=(
                    "该动作没有绑定 Operation；误填的 completed owner 不参与"
                    "操作结算，由已确认落点和区块效果结算，不以像素差异证明成功。"),
            )
        if (not report.outcome
                and report.parameter_info is not None
                and not any(
                    item.completed
                    for item in (
                        tuple(report.element_actions)
                        + tuple(report.region_actions)
                    ))):
            report = replace(report, parameter_info=None)
            self.ledger.event(
                "parameter_info_ignored_without_completed_owner",
                attempt_id=attempt.attempt_id,
                reason=(
                    "没有 completed owner；参数信息不能绑定到 Operation，"
                    "本次先按可见结果结算。"
                ),
            )
        attempt.after_ref = self.artifacts.save_attempt_after(
            attempt.attempt_id, screenshot)
        settled_operation_refs: Sequence[str] = ()
        framework_settled = not report.outcome
        delivery_error = str(
            getattr(self, "pending_action_error", "") or "")
        if delivery_error:
            report = replace(
                report,
                element_actions=(),
                region_actions=(),
                parameter_info=None,
                outcome="no_effect",
                task_result="retry",
                visible_result=delivery_error,
            )
            self.ledger.event(
                "action_delivery_error_overrode_completion",
                attempt_id=attempt.attempt_id,
                action_kind=str(attempt.action.get("kind") or ""),
                error=delivery_error,
            )
        elif framework_settled:
            settlement = settle_completed_actions(self.ledger, attempt, report)
            settled_operation_refs = settlement.operation_refs
            # Reuse the authoritative task settlement, not the service
            # operation's success, for the focus receipt and progress.
            primary_completed = attempt.task_id in settlement.task_refs
            # Accepted functional landing/effects, never image differences,
            # support an unbound navigation result. Unknown evidence stays unknown.
            unbound_visible_effect = bool(
                unbound_action
                and (self.ledger.current_state_id != attempt.source_state_id
                     or any(effect.get("cause") == "action" for effect in report.region_effects or ())))
            report = replace(
                report,
                outcome=(
                    "success" if (
                        settled_operation_refs or unbound_visible_effect) else
                    "uncertain"
                ),
                task_result="completed" if primary_completed else "retry",
                visible_result=report.reason,
            )
        attempt.outcome = report.outcome
        attempt.visible_result = report.visible_result
        attempt.target_state_id = self.ledger.current_state_id
        task = self.ledger.tasks.get(attempt.task_id)
        transition_action = dict(attempt.action)
        if (report.corrected_target
                and report.outcome == "success"
                and attempt.purpose == "execute"
                and task is not None
                and task.kind == "explore_operation"):
            operation = self.ledger.operations.get(task.operation_id)
            if operation is not None and report.corrected_target != operation.target:
                old_target = operation.target
                for occurrence_id in operation.source_occurrence_ids:
                    self.ledger.ensure_occurrence_variant(occurrence_id)
                identity = self.ledger.ensure_operation_identity(
                    operation.operation_id)
                source_occurrences = [
                    oid for oid in operation.source_occurrence_ids
                    if self.ledger.occurrences[oid].state_id
                    == attempt.source_state_id
                ]
                other_occurrences = [
                    oid for oid in operation.source_occurrence_ids
                    if oid not in source_occurrences
                ]
                if source_occurrences and other_occurrences:
                    split_id = self.ledger.mint("operation")
                    split_operation = Operation(
                        operation_id=split_id,
                        region_id=operation.region_id,
                        action=operation.action,
                        target=old_target,
                        status="pending",
                        reason=operation.reason,
                        source_occurrence_ids=other_occurrences,
                        variant_id=self.ledger.occurrences[
                            other_occurrences[0]].variant_id,
                        canonical_operation_id=(
                            identity.canonical_operation_id),
                        scope=operation.scope,
                        element_id=operation.element_id,
                        direction=operation.direction,
                    )
                    self.ledger.operations[split_id] = split_operation
                    self.ledger.regions[operation.region_id].operation_ids.append(
                        split_id)
                    identity.operation_ids.append(split_id)
                    split_variant = self.ledger.region_variants.get(
                        split_operation.variant_id)
                    if (split_variant is not None
                            and split_id not in split_variant.operation_ids):
                        split_variant.operation_ids.append(split_id)
                    source_element = self.ledger.elements.get(
                        split_operation.element_id)
                    if source_element is not None:
                        if source_element.variant_id != split_operation.variant_id:
                            split_element_id = self.ledger.mint("element")
                            split_element = Element(
                                element_id=split_element_id,
                                region_id=source_element.region_id,
                                variant_id=split_operation.variant_id,
                                name=source_element.name,
                                source_occurrence_ids=list(other_occurrences),
                            )
                            self.ledger.elements[split_element_id] = split_element
                            self.ledger.regions[
                                split_element.region_id].element_ids.append(
                                    split_element_id)
                            if split_variant is not None:
                                split_variant.element_ids.append(split_element_id)
                            split_operation.element_id = split_element_id
                            source_element = split_element
                        source_element.operation_ids.append(split_id)
                    split_task_id = self.ledger.mint("task")
                    self.ledger.tasks[split_task_id] = Task(
                        task_id=split_task_id,
                        kind="explore_operation",
                        status="pending",
                        state_id=self.ledger.occurrences[
                            other_occurrences[0]].state_id,
                        operation_id=split_id,
                        reason=operation.reason,
                        created_seq=len(self.ledger.tasks) + 1,
                    )
                    operation.source_occurrence_ids = source_occurrences
                    operation.variant_id = self.ledger.occurrences[
                        source_occurrences[0]].variant_id
                if any(
                        item != operation.operation_id
                        for item in identity.operation_ids):
                    identity.operation_ids = [
                        item for item in identity.operation_ids
                        if item != operation.operation_id
                    ]
                    canonical_operation_id = self.ledger.mint(
                        "canonical_operation")
                    identity = CanonicalOperation(
                        canonical_operation_id=canonical_operation_id,
                        region_id=operation.region_id,
                        action=operation.action,
                        target=report.corrected_target,
                        operation_ids=[operation.operation_id],
                        scope=operation.scope,
                        direction=operation.direction,
                    )
                    self.ledger.canonical_operations[
                        canonical_operation_id] = identity
                    self.ledger.regions[
                        operation.region_id].canonical_operation_ids.append(
                            canonical_operation_id)
                    operation.canonical_operation_id = canonical_operation_id
                else:
                    identity.target = report.corrected_target
                operation.target = report.corrected_target
                transition_action["target"] = report.corrected_target
                self.ledger.event(
                    "operation_target_corrected",
                    operation_ref=operation.operation_id,
                    attempt_id=attempt.attempt_id,
                    old_target=old_target,
                    corrected_target=report.corrected_target,
                    reason=report.reason,
                )
        if (report.outcome == "success"
                and attempt.source_state_id
                and attempt.target_state_id
                and attempt.source_state_id != attempt.target_state_id
                and attempt.purpose in {
                    "execute", "route", "survey", "recover"
                }):
            transition_id = self.ledger.mint("transition")
            transition = Transition(
                transition_id=transition_id,
                source_state_id=attempt.source_state_id,
                target_state_id=attempt.target_state_id,
                attempt_id=attempt.attempt_id,
                action=transition_action,
                visible_result=report.visible_result,
            )
            self.ledger.transitions.append(transition)
            refresh_transition_region_effects(self.ledger, transition)
        if (task is not None
                and not framework_settled
                and attempt.purpose == "execute"
                and attempt.action.get("operation_ref") == task.operation_id):
            self.scheduler.settle(
                self.ledger,
                task,
                result=report.task_result,
                reason=report.reason,
            )
            self._reconcile_verified_operation_reuse(task.operation_id)
        for operation_ref in settled_operation_refs:
            if task is None or operation_ref != task.operation_id:
                self._reconcile_verified_operation_reuse(operation_ref)
        self.ledger.add_history(
            task_id=attempt.task_id,
            purpose=attempt.purpose,
            action=str(attempt.action.get("kind") or ""),
            target=str(transition_action.get("target") or ""),
            parameters=transition_action,
            result=report.visible_result + "；" + report.reason,
            source_state_id=attempt.source_state_id,
            target_state_id=attempt.target_state_id,
        )
        self.ledger.event(
            "action_settled",
            attempt_id=attempt.attempt_id,
            outcome=report.outcome,
            task_result=report.task_result,
            target_state_id=attempt.target_state_id,
            after_ref=frame_ref,
        )
        if finalize:
            self._finish_pending_settlement()

    def _finish_pending_settlement(self, *, independent_known_landing: bool = False) -> bool:
        """Release pending only after the staged observation has been accepted."""
        if not self.pending_attempt_id:
            return False
        attempt = self.ledger.attempts[self.pending_attempt_id]
        task = self.ledger.tasks.get(attempt.task_id)
        isolated = False
        if attempt.outcome == 'uncertain':
            if independent_known_landing and task is not None and task.status in OPEN_TASK_STATES:
                reason = (f'{attempt.attempt_id} 结果仍未知；当前已知前景独立核验通过。'
                          '暂挂依赖该结果的任务，不重试原动作；保留缺口，由原调度选择其他适用操作。')
                self.scheduler.settle(self.ledger, task, result='deferred', reason=reason)
                self.ledger.event('action_result_gap_retained', attempt_ref=attempt.attempt_id,
                    task_ref=task.task_id, state_ref=self.ledger.current_state_id, reason=reason)
                isolated = True
            else:
                self.report_correction_stop_reason = 'action_result_unconfirmed'
                self.ledger.event('action_result_unconfirmed', attempt_ref=attempt.attempt_id,
                    state_ref=self.ledger.current_state_id, reason='No trustworthy action result or independent admitted continuation; stop before another GUI delivery')
        self._fail_repeated_no_effect_recovery(task)
        self._fail_repeated_no_effect_operation(task)
        self._fail_exhausted_task(task)
        if (getattr(self, "pending_report_correction", {}).get(
                "pending_attempt_ref") == attempt.attempt_id):
            self.pending_report_correction = {}
        self.pending_attempt_id = ""
        self.pending_before = b""
        self.pending_action_error = ""
        self.retained_effect_inventory = None
        return isolated

    def _fail_repeated_no_effect_recovery(
        self,
        task: Optional[Task],
    ) -> bool:
        if task is not None and task.status != "active":
            return False
        task_id = task.task_id if task is not None else ""
        count = 0
        for attempt in reversed(list(self.ledger.attempts.values())):
            if attempt.task_id != task_id:
                break
            if attempt.purpose != "recover" or attempt.outcome != "no_effect":
                break
            count += 1
        if count < MAX_NO_EFFECT_RECOVERY_ATTEMPTS:
            return False
        if task is None:
            self.taskless_recovery_error = (
                f"无活动任务时连续 {count} 次恢复均无可见效果；"
                "停止本轮遍历，保留动作证据与恢复缺口。")
            self.ledger.event(
                "taskless_recovery_exhausted",
                attempt_id=next(reversed(self.ledger.attempts)),
                attempt_count=count,
                reason=self.taskless_recovery_error,
            )
            return True
        restarted = getattr(self, "restarted_recovery_task_ids", set())
        if (is_android(getattr(self, "platform", "desktop"))
                and task.task_id not in restarted):
            self.restart_recovery_task_id = task.task_id
            self.ledger.event(
                "recovery_process_restart_requested",
                task_id=task.task_id,
                operation_id=task.operation_id,
                attempt_count=count,
                reason=(
                    "连续 recover 无可见效果；下一步执行不清数据的 "
                    "force-stop + relaunch。"
                ),
            )
            return False
        reason = (
            f"当前任务连续 {count} 次真实 recover 均无可见效果；"
            "且不清数据的进程重启后仍未恢复；保留 failed gap 并继续其他任务。"
        )
        self.scheduler.settle(
            self.ledger, task, result="failed", reason=reason)
        self.ledger.event(
            "recovery_no_effect_budget_exhausted",
            task_id=task.task_id,
            operation_id=task.operation_id,
            attempt_count=count,
            reason=reason,
        )
        return True

    def _perform_requested_restart(self) -> Dict[str, Any]:
        task_id = str(getattr(self, "restart_recovery_task_id", "") or "")
        if not task_id:
            return {}
        self.restart_recovery_task_id = ""
        self.restarted_recovery_task_ids.add(task_id)
        observation = self.scope.restart_preserving_data()
        self.confirmed_state_id = ""
        self.confirmed_screenshot = b""
        self.correction = (
            "连续恢复动作无效，框架已关闭目标应用进程并在保留数据的情况下"
            "重新打开；请只根据这张 fresh screenshot 重新识别当前位置。"
        )
        self.ledger.event(
            "recovery_process_restarted",
            task_id=task_id,
            reason="force-stop + relaunch without pm clear",
        )
        return dict(observation or {})

    def _fail_repeated_no_effect_operation(
        self,
        task: Optional[Task],
    ) -> bool:
        if (task is None or task.status != "active"
                or task.kind != "explore_operation" or not task.operation_id):
            return False
        focus_operation = self.ledger.operations.get(task.operation_id)
        focus_canonical = (
            focus_operation.canonical_operation_id
            if focus_operation is not None else "")
        latest = next((
            attempt for attempt in reversed(list(self.ledger.attempts.values()))
            if attempt.task_id == task.task_id
            and attempt.purpose == "execute"
        ), None)
        if latest is None or latest.outcome != "no_effect":
            return False
        actual_operation_id = str(
            latest.action.get("operation_ref") or "")
        actual_operation = self.ledger.operations.get(actual_operation_id)

        def same_focus_operation(operation_id: str) -> bool:
            if operation_id == task.operation_id:
                return True
            operation = self.ledger.operations.get(operation_id)
            return bool(
                focus_canonical
                and operation is not None
                and operation.canonical_operation_id == focus_canonical
            )

        if not same_focus_operation(actual_operation_id):
            return False
        source_state_id = latest.source_state_id
        count = 0
        for attempt in reversed(list(self.ledger.attempts.values())):
            if (attempt.task_id == task.task_id
                    and attempt.purpose == "execute"
                    and attempt.source_state_id == source_state_id
                    and same_focus_operation(str(
                        attempt.action.get("operation_ref") or ""))
                    and attempt.outcome == "no_effect"):
                count += 1
        if count < MAX_NO_EFFECT_OPERATION_ATTEMPTS:
            return False
        canonical_operation_id = (
            actual_operation.canonical_operation_id
            if actual_operation is not None else focus_canonical)
        reason = (
            f"同一规范 Operation 已在 State {source_state_id} 的 fresh-frame "
            f"grounding 后执行 {count} 次，"
            "仍无可见直接效果；记录为 grounding 或应用校验 gap，"
            "不再把无效点击标记为成功。"
        )
        self.scheduler.settle(
            self.ledger, task, result="failed", reason=reason)
        self.ledger.event(
            "operation_no_effect_retry_exhausted",
            task_id=task.task_id,
            operation_id=task.operation_id,
            actual_operation_id=actual_operation_id,
            canonical_operation_id=canonical_operation_id,
            source_state_id=source_state_id,
            attempt_count=count,
            reason=reason,
        )
        return True

    def _fail_exhausted_task(self, task: Optional[Task]) -> bool:
        if task is None or task.status != "active":
            return False
        if task.kind == "explore_operation":
            limit = MAX_OPERATION_ATTEMPTS
            event_kind = "operation_attempt_budget_exhausted"
            subject = "当前操作探索任务（包含导航和其他准备动作）"
        elif task.kind == "survey_page":
            limit = MAX_SURVEY_ATTEMPTS
            event_kind = "survey_attempt_budget_exhausted"
            subject = "当前页面调查"
        else:
            return False
        if task.attempt_count < limit:
            return False
        reason = (
            f"{subject}已执行 {task.attempt_count} 次真实动作仍未完成；"
            "为避免单个任务耗尽全局动作预算，记录为 failed 并继续其他任务。"
        )
        self.scheduler.settle(
            self.ledger, task, result="failed", reason=reason)
        self.ledger.event(
            event_kind,
            task_id=task.task_id,
            attempt_count=task.attempt_count,
            reason=reason,
            **({"operation_id": task.operation_id}
               if task.operation_id else {}),
        )
        return True

    def _unconfirmed_current_binding(self, operation_ref: str) -> Optional[ActionAttempt]:
        for attempt in reversed(self.ledger.attempts.values()):
            if (attempt.action.get('kind') in {'back', 'wait'}
                    and not attempt.action.get('operation_ref')):
                continue
            if (attempt.outcome == 'uncertain'
                    and attempt.source_state_id == self.ledger.current_state_id
                    and attempt.action.get('operation_ref') == operation_ref):
                return attempt
            break
        return None

    def _completion_reason(self, system_scope: str, screenshot: bytes) -> str:
        # Byte equality only checks the provenance of this accepted frame; it
        # does not decide semantic identity or whether an action succeeded.
        if (system_scope != 'target'
                or self.confirmed_state_id != self.ledger.current_state_id
                or not self.confirmed_screenshot
                or screenshot != self.confirmed_screenshot
                or not self.ledger.state_occurrences(self.ledger.current_state_id)):
            return 'foreground_inventory_unconfirmed'
        return 'terminal_gaps' if self.scheduler.gaps(self.ledger) else 'complete'

    def _progress_phase(self, task: Optional[Task]) -> Dict[str, Any]:
        """Choose the control phase; the Agent still verifies pixels and safety."""
        work = getattr(getattr(self, 'scheduler', None), 'work_region_id', '')
        result = {'work_region_ref': work}
        if self.pending_attempt_id:
            return {**result, 'phase':'settle', 'instruction':'先观察并结算已投递动作，不投递新动作或重复查询目标。'}
        if (getattr(self, 'resume_region_rediscovery_required', False)
                or getattr(self, 'confirmed_state_id', '') != self.ledger.current_state_id
                or not self.ledger.current_state_id):
            return {**result, 'phase':'observe', 'instruction':'先确认当前可交互前景和位置；历史来源不是当前位置。'}
        operation = self.ledger.operations.get(task.operation_id) if task else None
        if operation is None:
            return {**result, 'phase':'observe', 'instruction':'补充本次需要的观察；不要求无关清单全部完整。'}
        from .partition_review import qualification_gaps
        if operation.operation_id in qualification_gaps(self.ledger):
            route = plan_region_route(self.ledger, current_state_id=self.ledger.current_state_id,
                target_region_id=operation.region_id)
            return {**result, 'phase': 'navigate' if route['status'] == 'ready' else 'observe',
                'route': route, 'qualification_gap': qualification_gaps(self.ledger)[operation.operation_id],
                'instruction': '沿可信路线复查目标Region；到达后提交带已有owner/co的当前清单，由原审核核对新资格证据。路线或新截图不解除限制，不执行争议操作。'}
        binding = current_operation_binding(self.ledger, operation.operation_id)
        unresolved = self._unconfirmed_current_binding(binding.operation_id) if binding else None
        if unresolved is not None:
            return {**result, 'phase':'observe', 'unconfirmed_attempt_ref':unresolved.attempt_id,
                    'instruction':'同源绑定的上一动作结果仍uncertain；fresh位置确认不是动作结果恢复。禁止原样重发，先核对当前证据，必要时只做合法恢复/准备；不能追改旧结果或伪造完成。'}
        if binding is not None and binding.status not in {'deferred','failed','cancelled'}:
            return {**result, 'phase':'execute', 'operation_ref':binding.operation_id,
                    'owner_ref':binding.element_id or binding.region_id,
                    'instruction':'目标已有适用本地绑定，核对当前截图和动作安全后执行；不另选独立任务。'}
        route = plan_region_route(self.ledger, current_state_id=self.ledger.current_state_id,
                                  target_region_id=operation.region_id, target_operation_id=operation.operation_id)
        if route['status']=='ready' and route['steps']:
            return {**result, 'phase':'navigate', 'next_step':route['steps'][0],
                    'instruction':'程序已选定路线第一步；只定位此步当前owner，不再查询目标在本屏的绑定。导航后先核对落点，再继续原任务。'}
        return {**result, 'phase':'prepare', 'route_status':route['status'],
                'instruction':'目标无当前适用绑定且无可信路线；不要反复查找被前景接管的背景控件owner。'
                    '先根据当前图判断是否能安全收起前景；桌面back实际是Esc，Android是系统返回，不等于可见返回按钮。'
                    '点击可见返回按钮须使用click和当前绑定owner/point；仅在证据支持系统返回能安全收起时使用无owner的back，仍须动作校验及落点结算。'
                    '这是服务当前工作Region的准备，不是放弃目标，也不是重放旧Attempt。没有安全准备就说明缺条件，不为凑动作伪造绑定或完成。'}

    def _context_lookup_scope(self) -> str:
        if self.pending_attempt_id:
            return self.pending_attempt_id
        import hashlib
        from .region_work import region_signature
        task = self.ledger.current_task()
        operation = self.ledger.operations.get(task.operation_id) if task else None
        evidence = region_signature(self.ledger, operation.region_id) if operation else ()
        digest = hashlib.sha256(repr(evidence).encode()).hexdigest()[:16]
        return (f'state:{self.ledger.current_state_id}:task:{task.task_id if task else ""}'
                f':knowledge:{len(self.ledger.operations)}:{len(self.ledger.transitions)}:{digest}')


    def _handle_context_lookup_exhaustion(self, task: Optional[Task], *, reason: str, frame_ref: str) -> bool:
        if (self.pending_attempt_id or self.resume_region_rediscovery_required
                or not self.ledger.current_state_id
                or self.confirmed_state_id != self.ledger.current_state_id
                or self._report_budget().count or task is None or task.kind != 'explore_operation'):
            return False
        self.scheduler.settle(self.ledger, task, result='deferred', reason='查询未带来新绑定/路线，局部暂挂：'+reason)
        self.ledger.event('task_lookup_deferred', task_ref=task.task_id,
            work_region_ref=self.scheduler.work_region_id, state_ref=self.ledger.current_state_id,
            screenshot_ref=frame_ref, reason=reason, retry_requires='new applicable binding, route or corrected evidence')
        self.correction='当前目标缺口已保留；继续本区其他适用直属操作，确实全部受阻才换区。'
        self.last_context_task_id=None
        return True

    def _request_context_lookup(self, turn: AgentTurn, *, frame_ref: str) -> None:
        scope = self._context_lookup_scope()
        if self.context_lookup_scope != scope:
            self.context_lookup_scope, self.context_lookup_queries = scope, []
        if isinstance(turn.context_query, dict):
            for field, records in (("state_ref", self.ledger.states), ("region_ref", self.ledger.regions)):
                ref = turn.context_query.get(field)
                if ref and ref not in records:
                    raise ValueError(f"context_query.{field}={ref}不存在；不能用未知编号筛选。")
            query = json.dumps(turn.context_query, ensure_ascii=False, sort_keys=True).casefold()
        else:
            query = " ".join(turn.context_query.casefold().split())
        phase = self._progress_phase(self.ledger.current_task())
        needs_navigation = phase['phase'] in {'navigate','prepare'} and bool(self.context_lookup_queries)
        if needs_navigation and getattr(self, 'context_navigation_redirect', '') != scope:
            self.context_navigation_redirect=scope
            self.correction=phase['instruction']
            self.last_context_task_id=None
            self.ledger.event('context_lookup_redirected', phase=phase['phase'],
                task_ref=self.ledger.current_task_id, screenshot_ref=frame_ref,
                reason='Same position/target/knowledge: continue navigation or bounded preparation, not another lookup')
            return
        if needs_navigation or query in self.context_lookup_queries or len(self.context_lookup_queries) >= 2:
            raise ContextLookupExhausted("本观察阶段的检索查询重复或已达两次上限；保留pending，不原样重复请求。")
        self.context_lookup_queries.append(query)
        self.context_lookup_query = turn.context_query
        self.ledger.event("context_lookup_requested", query=turn.context_query,
                          pending_attempt_ref=self.pending_attempt_id, screenshot_ref=frame_ref,
                          gui_action=False)

    def _apply_region_refinement(self, turn: AgentTurn, *, screenshot: bytes, frame_ref: str) -> None:
        from .region_refinement import refine_regions
        if (self.pending_attempt_id or turn.previous_action is not None
                or turn.action is not None or turn.page_report is not None
                or turn.next_operation_ref or turn.current_task_result
                or turn.representative_probe is not None
                or not self.ledger.current_state_id
                or (turn.screen is None and self.confirmed_state_id != self.ledger.current_state_id)
                or (turn.screen is not None and (
                    turn.screen.identity != "known"
                    or turn.screen.state_ref != self.ledger.current_state_id
                    or turn.screen.page_ref != self.ledger.current_page_id))
                or self.resume_region_rediscovery_required):
            raise ValueError("region_refinement requires settled, confirmed current location and no other action/report")
        self.ledger = refine_regions(
            self.ledger, turn.region_refinement, agent=self.agent,
            current_state_id=self.ledger.current_state_id,
            screenshot=screenshot, screenshot_ref=frame_ref,
            read_screenshot=lambda ref: (self.artifacts.root / ref).read_bytes(),
            corrections=self._report_budget(),
        )
        self._flush_report_corrections()
        self._report_budget().reset()
        self.correction = "分区修正已提交，控件归属与已确认共享身份已更新；未执行GUI，使用当前绑定继续。"
        self.last_context_task_id = None

    def _clear_action_rejections(self) -> None:
        self.rejection_task_id = ""
        self.rejection_issue = ""
        self.rejection_streak = 0

    def _record_action_rejection(
        self,
        task: Optional[Task],
        issue: str,
    ) -> bool:
        task_id = task.task_id if task is not None else ""
        count = 0
        if task is not None and task.kind == "explore_operation":
            if self.rejection_task_id == task_id:
                self.rejection_streak += 1
            else:
                self.rejection_task_id = task_id
                self.rejection_streak = 1
            self.rejection_issue = issue
            count = self.rejection_streak
        else:
            self._clear_action_rejections()
        self.correction = f"本轮提议的动作未执行。{issue}"
        self.ledger.event(
            "action_rejected",
            task_id=task_id,
            reason=issue,
            consecutive_count=count,
        )
        if (task is None
                or task.kind != "explore_operation"
                or count < MAX_CONSECUTIVE_ACTION_REJECTIONS):
            return False
        reason = (
            f"当前操作连续 {count} 次收到框架动作纠正仍无真实进展；"
            "为避免拒绝循环，记录为 failed 并继续其他任务。"
        )
        self.scheduler.settle(
            self.ledger, task, result="failed", reason=reason)
        self.ledger.event(
            "operation_rejection_budget_exhausted",
            task_id=task.task_id,
            operation_id=task.operation_id,
            consecutive_count=count,
            reason=reason,
        )
        self._clear_action_rejections()
        self.correction = ""
        return True

    def _current_region_route_ready(self, task: Optional[Task]) -> bool:
        if task is None or task.kind != "explore_operation":
            return False
        operation = self.ledger.operations.get(task.operation_id)
        if operation is None:
            return False
        if current_operation_binding(self.ledger, task.operation_id) is not None:
            return True
        route = plan_region_route(
            self.ledger,
            current_state_id=self.ledger.current_state_id,
            target_region_id=operation.region_id,
            target_operation_id=operation.operation_id,
        )
        return route["status"] == "ready"

    def _inventory_facts(self) -> Dict[str, Any]:
        """Progress comes from bindings and statuses, not rewritten prose."""
        facts = current_page_record(self.ledger)
        facts["inventory_report_pending"] = (
            self.ledger.current_state_id in deferred_inventory_reports(self.ledger))
        for key in ("page_name", "page_summary", "state_name", "state_summary"):
            facts.pop(key, None)
        for region in facts.get("regions", []):
            for key in ("name", "summary", "memory"):
                region.pop(key, None)
            operations = list(region["region_operations"])
            for element in region["elements"]:
                element.pop("name", None)
                observation = element.get("last_observation")
                if isinstance(observation, dict):
                    element["last_observation"] = observation.get("description", "")
                operations.extend(element["operations"])
            for operation in operations:
                if operation.get("parameter_status") in {"none", "observed"}:
                    operation["parameter_status"] = "known"
                for key in ("target", "reason", "result", "parameter_summary",
                            "parameter_evidence_refs"):
                    operation.pop(key, None)
        return facts

    def _verified_operation_attempt(
        self,
        operation_id: str,
    ) -> Optional[ActionAttempt]:
        for attempt in reversed(list(self.ledger.attempts.values())):
            if (attempt.purpose == "execute"
                    and attempt.outcome == "success"
                    and attempt.action.get("operation_ref") == operation_id
                    and attempt.visible_result
                    and attempt.after_ref):
                return attempt
        return None

    def _reconcile_verified_operation_reuse(
        self,
        operation_id: str,
    ) -> None:
        current = self.ledger.operations.get(operation_id)
        if (current is None
                or current.status != "verified"
                or not current.reuse_candidate_operation_id):
            return
        known_id = current.reuse_candidate_operation_id
        known = self.ledger.operations.get(known_id)
        current_attempt = self._verified_operation_attempt(operation_id)
        known_attempt = self._verified_operation_attempt(known_id)
        if (known is None
                or known.status != "verified"
                or current_attempt is None
                or known_attempt is None):
            return
        try:
            effect = compare_action_effects(
                self.artifacts.read(known_attempt.before_ref),
                self.artifacts.read(known_attempt.after_ref),
                self.artifacts.read(current_attempt.before_ref),
                self.artifacts.read(current_attempt.after_ref),
            )
        except OSError:
            return
        if not effect.accepted:
            current.reuse_candidate_operation_id = ""
            self.ledger.event(
                "operation_reuse_visual_effect_unresolved",
                current_operation_id=operation_id,
                known_operation_id=known_id,
                score=round(effect.score, 4),
                edge_score=round(effect.edge_score, 4),
                area_ratio=round(effect.area_ratio, 4),
                reason="两次真实点击的主要可见变化不能程序性确认相同",
            )
            return
        self.ledger = merge_operation_identity(
            self.ledger,
            current_operation_id=operation_id,
            known_operation_id=known_id,
            reason=(
                "区块复核已提出候选配对，且两边真实点击的主要可见变化"
                f"一致（gray={effect.score:.3f}, edge={effect.edge_score:.3f}）"
            ),
        )

    def _replayable_route_transition(
        self,
        *,
        task: Task,
    ) -> Optional[Transition]:
        current = self.ledger.current_state_id
        targets = task_source_states(self.ledger, task)
        if not current or current in targets or not targets:
            return None
        operation = self.ledger.operations.get(task.operation_id)
        if operation is not None:
            route = plan_region_route(self.ledger, current_state_id=current,
                target_region_id=operation.region_id, target_operation_id=operation.operation_id)
            if route['status'] == 'ready' and route['steps']:
                first = route['steps'][0]
                transition = next((t for t in self.ledger.transitions
                    if t.transition_id == first['evidence_transition_ref']), None)
                attempt = self.ledger.attempts.get(first['evidence_attempt_ref'])
                if (transition is not None and attempt is not None and attempt.outcome == 'success'
                        and attempt.anchor_ref and len(attempt.anchor_offset_px) == 2
                        and transition.action.get('kind') == 'click'):
                    return transition
                # The graph still selects this step; the Agent supplies its
                # current visual location when no reusable anchor is available.
                return None
        adjacency: Dict[str, List[Transition]] = {}
        for transition in self.ledger.transitions:
            attempt = self.ledger.attempts.get(transition.attempt_id)
            if (attempt is None
                    or attempt.outcome != "success"
                    or not attempt.anchor_ref
                    or len(attempt.anchor_offset_px) != 2
                    or transition.action.get("kind") != "click"):
                continue
            adjacency.setdefault(transition.source_state_id, []).append(
                transition)
        queue = deque([current])
        first_hop: Dict[str, Transition] = {}
        seen = {current}
        while queue:
            source = queue.popleft()
            for transition in adjacency.get(source, []):
                target = transition.target_state_id
                if target in seen:
                    continue
                seen.add(target)
                first_hop[target] = (
                    transition if source == current else first_hop[source])
                if target in targets:
                    return first_hop[target]
                queue.append(target)
        return None

    def _visual_anchor_route_action(
        self,
        *,
        task: Task,
        screenshot: bytes,
    ) -> Optional[ActionRequest]:
        if (self.confirmed_state_id != self.ledger.current_state_id
                or not self.confirmed_screenshot
                or screenshot != self.confirmed_screenshot):
            return None
        transition = self._replayable_route_transition(task=task)
        if transition is None:
            return None
        attempt = self.ledger.attempts[transition.attempt_id]
        try:
            anchor = self.artifacts.read(attempt.anchor_ref)
        except OSError:
            return None
        match = relocate_click_anchor(
            anchor,
            attempt.anchor_offset_px,
            screenshot,
        )
        if match is None:
            return None
        action = ActionRequest(
            kind="click",
            purpose="route",
            target=str(transition.action.get("target") or "已验证路线入口"),
            point_1000=match.point_1000,
            text="",
            direction="",
            amount=650,
            operation_ref="",
        )
        if self._validate_action(task, action):
            return None
        self.ledger.event(
            "visual_anchor_route_replayed",
            task_id=task.task_id,
            source_state_id=transition.source_state_id,
            expected_target_state_id=transition.target_state_id,
            original_attempt_id=attempt.attempt_id,
            point_1000=list(match.point_1000),
            score=round(match.score, 4),
            margin=round(match.margin, 4),
            edge_score=round(match.edge_score, 4),
            edge_margin=round(match.edge_margin, 4),
        )
        return action

    def _normalize_page_report_refs_for_state(
        self,
        *,
        report: PageReport,
        state_id: str,
        screen_identity: str,
    ) -> PageReport:
        if screen_identity not in {"new_page", "new_state"}:
            return report
        visible_region_ids = {
            item.region_id for item in self.ledger.state_occurrences(state_id)}
        regions = []
        for region in report.regions:
            if region.region_ref in visible_region_ids:
                regions.append(region)
                continue
            if region.region_ref and region.region_ref not in self.ledger.regions:
                regions.append(region)
                continue
            elements = tuple(replace(
                element,
                element_ref="",
                operations=tuple(
                    replace(operation, operation_ref="")
                    for operation in element.operations),
            ) for element in region.elements)
            if region.region_ref or any(
                    element.element_ref for element in region.elements):
                self.ledger.event(
                    "new_state_inventory_refs_deferred",
                    state_id=state_id,
                    suggested_region_ref=region.region_ref,
                    suggested_element_refs=[
                        element.element_ref for element in region.elements
                        if element.element_ref],
                )
            regions.append(replace(
                region,
                region_ref="",
                elements=elements,
                region_operations=tuple(
                    replace(operation, operation_ref="")
                    for operation in region.region_operations),
            ))
        for index, region in enumerate(regions):
            if (isinstance(region.parent_ref, str) and region.parent_ref
                    and region.parent_ref not in visible_region_ids):
                matches = [i for i, original in enumerate(report.regions)
                           if original.region_ref == region.parent_ref]
                if len(matches) == 1:
                    regions[index] = replace(region, parent_ref=matches[0])
        return replace(report, regions=tuple(regions))

    def _partition_scope(self, report, context):
        from .partition_review import operation_paths
        scope = dict(context.get('探索范围', {}))
        scope.update(target_app=self.app_name, platform=self.platform)
        limits = []
        declarations = getattr(self.scheduler, 'region_declarations', {})
        for path, proposal in operation_paths(report).items() if report else []:
            operation = self.ledger.operations.get(proposal.operation_ref)
            reference = operation.canonical_operation_id if operation else proposal.operation_ref
            for declaration in declarations.values():
                for field in ('restricted', 'conditions'):
                    if reference and reference in declaration.get(field, {}):
                        limits.append({'path': path, 'constraint': field, 'reason': declaration[field][reference]})
        if limits:
            scope['operation_limits'] = limits
        return scope

    def _known_action_candidate(self, task, screenshot):
        if (self.pending_attempt_id or not screenshot
                or self.confirmed_state_id != self.ledger.current_state_id
                or self.confirmed_screenshot != screenshot):
            return None
        phase = self._progress_phase(task)
        operation_ref = (phase.get('operation_ref') if phase['phase'] == 'execute'
                         else phase.get('next_step', {}).get('operation_ref'))
        operation = self.ledger.operations.get(operation_ref)
        if operation is None or operation.action in {'input_text', 'back', 'wait'}:
            return None
        if operation.status in {'deferred', 'failed', 'cancelled'}:
            return None
        owner = operation.element_id if operation.scope == 'element' else operation.region_id
        try:
            resolved = resolve_action_operation(self.ledger, state_id=self.ledger.current_state_id,
                owner_ref=owner, action=operation.action, direction=operation.direction)
        except ValueError:
            return None
        if resolved != operation.operation_id:
            return None
        return {'state_ref': self.ledger.current_state_id, 'task_ref': task.task_id if task else '',
            'image_sha256': hashlib.sha256(screenshot).hexdigest(),
            'operation_ref': operation.operation_id, 'owner_ref': owner,
            'kind': operation.action, 'target': operation.target, 'direction': operation.direction}

    def _bind_action(
        self,
        task: Optional[Task],
        action: ActionRequest,
    ) -> ActionRequest:
        """Turn the model's owner action into framework-internal routing data."""
        if action.owner_ref == '@current':
            offered = getattr(self, 'offered_action_candidate', None)
            current = self._known_action_candidate(task, self.confirmed_screenshot)
            if (not offered or current != offered or action.purpose or action.operation_ref
                    or action.kind != offered['kind'] or action.target != offered['target']
                    or action.direction != offered['direction'] or action.text):
                raise ValueError('action.owner_ref=@current：候选失效、不唯一或动作/目标/参数不匹配；未投递，不替换成其他目标。')
            action = replace(action, owner_ref=offered['owner_ref'])
            self.ledger.event('known_action_confirmed', protocol='owner_confirmation.v1',
                candidate=offered, model_confirmation='@current', generated_owner=action.owner_ref)
        if action.purpose:
            return action
        if action.owner_ref:
            operation_ref = resolve_action_operation(
                self.ledger,
                state_id=self.ledger.current_state_id,
                owner_ref=action.owner_ref,
                action=action.kind,
                direction=action.direction,
            )
            purpose = "execute"
            operation = self.ledger.operations.get(operation_ref)
            if (task is not None
                    and task.kind == "survey_page"
                    and task.state_id == self.ledger.current_state_id
                    and operation is not None
                    and operation.scope == "region"
                    and operation.action == "scroll"):
                purpose = "survey"
            return replace(
                action, purpose=purpose, operation_ref=operation_ref)
        if task is not None and task.kind == "survey_page":
            purpose = (
                "survey" if self.ledger.current_state_id == task.state_id
                else "route"
            )
        elif (task is not None
                and self.ledger.current_state_id not in task_source_states(
                    self.ledger, task)):
            purpose = "route"
        else:
            purpose = "recover"
        return replace(action, purpose=purpose, operation_ref="")

    @staticmethod
    def _near_repeated_detour(
        previous: ActionAttempt,
        action: ActionRequest,
    ) -> bool:
        requested = action_dict(action)
        if any(
            previous.action.get(key) != requested.get(key)
            for key in ("kind", "operation_ref", "direction", "text")
        ):
            return False
        old_point = previous.action.get("point_1000")
        new_point = requested.get("point_1000")
        if (not isinstance(old_point, list) or len(old_point) != 2
                or not isinstance(new_point, list) or len(new_point) != 2):
            return previous.action == requested
        distance_squared = sum(
            (float(old) - float(new)) ** 2
            for old, new in zip(old_point, new_point)
        )
        return distance_squared <= DETOUR_POINT_REPEAT_RADIUS_1000 ** 2

    def _validate_action(self, task: Optional[Task], action: ActionRequest) -> str:
        from .partition_review import qualification_gaps
        if action.operation_ref in qualification_gaps(self.ledger):
            return '当前本地操作资格仍有审核缺口；先复查身份和资格，不能投递。'
        operation = self.ledger.operations.get(action.operation_ref)
        if operation is not None and operation.status == 'deferred':
            return f'当前操作仍暂缓，先取得原前提/范围内的新资格证据：{operation.reason}'
        declaration = getattr(getattr(self, 'scheduler', None), 'region_declarations', {}).get(
            operation.region_id if operation else '', {})
        if operation is not None:
            ref = operation.canonical_operation_id or operation.operation_id
            for field in ('restricted', 'conditions'):
                if ref in declaration.get(field, {}):
                    return f"工作范围中的操作仍受限/待条件：{declaration[field][ref]}；不因树中可见而获得执行许可。"
        unresolved = self._unconfirmed_current_binding(action.operation_ref) if action.operation_ref else None
        if unresolved is not None:
            return (f'{unresolved.attempt_id} 的同源绑定仍为 uncertain；fresh 或 Back只恢复前景，'
                    '不代表原失败已解决。不能立即原样重复未知结果的动作；先核对结果或通过合法准备取得新的适用来源/绑定。')
        issue = validate_for_platform(action, platform=self.platform)
        if issue:
            return issue
        if action.owner_ref and action.operation_ref:
            returned = False
            for previous in reversed(self.ledger.attempts.values()):
                if (previous.action.get("kind") == "back"
                        and not previous.action.get("owner_ref")
                        and not previous.action.get("operation_ref")):
                    returned = True
                    continue
                if (returned and previous.source_state_id == self.ledger.current_state_id
                        and previous.outcome in {"no_effect", "uncertain"}
                        and self._near_repeated_detour(previous, action)):
                    return (f"{previous.attempt_id}的同一操作仍无效果或不确定；Back只恢复前景，"
                            "不代表原失败已解决。不能只收起菜单后原样重试；请核对具体控件、"
                            "采用实质不同的落点/参数或其他可见路径。")
                break
        if is_android(self.platform) and action.kind == "scroll":
            keyboard_check = getattr(
                self.env, "is_soft_keyboard_visible", None)
            if callable(keyboard_check):
                try:
                    keyboard_visible = keyboard_check()
                except Exception:
                    keyboard_visible = None
                if keyboard_visible is True:
                    return (
                        "Android 软键盘仍可见，不能执行 scroll；请先用 back "
                        "隐藏键盘，取得 fresh screenshot 后再从目标应用内容区域"
                        "选择滚动点。"
                    )
        if (action.kind == "scroll"
                and (not action.owner_ref or not action.operation_ref)):
            return (
                "scroll 必须绑定当前可见 Region 的 region_ref 和"
                "对应方向 RegionOperation；不允许空 owner 滚动。"
            )
        if task is None:
            if (action.purpose == "recover"
                    and not action.owner_ref and not action.operation_ref):
                return ""
            operation = self.ledger.operations.get(action.operation_ref)
            if (getattr(self, "exploration_goal", "") and action.owner_ref
                    and operation is not None and operation.status in {"recorded", "verified"}):
                try:
                    expected = resolve_action_operation(
                        self.ledger, state_id=self.ledger.current_state_id,
                        owner_ref=action.owner_ref, action=action.kind, direction=action.direction)
                except ValueError as exc:
                    return str(exc)
                if expected == action.operation_ref:
                    previous = next(reversed(self.ledger.attempts.values()), None)
                    if (previous is not None and not previous.task_id
                            and previous.source_state_id == self.ledger.current_state_id
                            and previous.outcome in {"no_effect", "uncertain"}
                            and self._near_repeated_detour(previous, action)):
                        return "上一恢复控件动作无效果或不确定；先核对最新图并纠正落点或恢复条件，不能原样重复。"
                    return ""
                return f"action.owner_ref={action.owner_ref} 当前绑定为 {expected}，收到 {action.operation_ref}。"
            return "当前没有可运行任务，只能执行不绑定功能操作的恢复动作"
        if task.kind == "explore_operation":
            requested = action_dict(action)
            repeated = 0
            for attempt in reversed(list(self.ledger.attempts.values())):
                if attempt.task_id != task.task_id:
                    continue
                if (attempt.outcome != "no_effect"
                        or attempt.action != requested):
                    break
                repeated += 1
            if repeated >= 3:
                return (
                    f"同一任务已连续 {repeated} 次以完全相同参数执行且均无可见"
                    "效果，不能再次原样投递。请改变点位、方向或幅度等可验证"
                    "参数；达到确定性尝试上限后，框架会自动保留 failed gap。"
                )
        if task.kind == "survey_page":
            if action.kind == "scroll":
                repeated_direction = 0
                for attempt in reversed(list(self.ledger.attempts.values())):
                    if attempt.task_id != task.task_id:
                        continue
                    if (attempt.outcome != "no_effect"
                            or attempt.action.get("kind") != "scroll"
                            or attempt.action.get("owner_ref") != action.owner_ref
                            or attempt.action.get("direction")
                            != action.direction):
                        break
                    repeated_direction += 1
                if repeated_direction >= 3:
                    opposite = (
                        "down" if action.direction == "up" else "up"
                        if action.direction == "down" else "另一方向"
                    )
                    return (
                        f"页面调查已连续 {repeated_direction} 次向 "
                        f"{action.direction} 滚动且都无可见效果，不能继续只改"
                        "点位重复同一方向。direction 表示要查看的内容方向："
                        "查看视口下方用 down，查看上方用 up。请改用 "
                        f"direction={opposite}、改变调查区域，或在现有证据"
                        "足够时提交 survey_complete=true。"
                    )
            away_from_source = self.ledger.current_state_id != task.state_id
            if action.owner_ref and action.operation_ref:
                try:
                    expected = resolve_action_operation(
                        self.ledger, state_id=self.ledger.current_state_id,
                        owner_ref=action.owner_ref, action=action.kind,
                        direction=action.direction)
                except ValueError as exc:
                    return str(exc)
                if action.operation_ref != expected:
                    return f"action.owner_ref={action.owner_ref} 当前绑定为 {expected}，收到 {action.operation_ref}。"
                return ""
            allowed = {"route", "recover"} if away_from_source else {
                "survey", "recover"}
            if action.purpose not in allowed:
                if away_from_source:
                    return (
                        f"当前调查任务属于 {task.state_id}，当前位置是 "
                        f"{self.ledger.current_state_id}；请用当前可见且已登记的 "
                        "owner 逐步返回来源状态，再提交完整 page_report。"
                    )
                return (
                    "调查动作需要当前已登记的 owner_ref；未知控件先补清单，"
                    "取得绑定后可继续调查，不要求清点提前完成。"
                )
            if (action.operation_ref
                    and not (action.kind == "scroll"
                             and action.owner_ref in self.ledger.regions)):
                return (
                    f"页面清点任务 {task.task_id} 的操作 {action.operation_ref} 缺少当前 owner_ref。"
                )
        if task.kind == "explore_operation":
            if action.owner_ref and action.purpose == "execute":
                operation = self.ledger.operations.get(action.operation_ref)
                if operation is None:
                    return (f"action.owner_ref={action.owner_ref} 没有映射到当前 Variant 的 Operation "
                            f"（绑定结果 {action.operation_ref!r}）；请核对当前已登记 owner，缺少操作时先补清单。")
                if operation.action != action.kind:
                    return (f"action.kind={action.kind} 与 owner_ref={action.owner_ref} 映射的 Operation "
                            f"{operation.operation_id} 动作 {operation.action} 不一致；请使用该 owner 已登记的动作或补充真实的新操作。")
                if (operation.scope == "region"
                        and operation.direction != action.direction):
                    return (f"action.direction={action.direction} 与 owner_ref={action.owner_ref} 映射的 "
                            f"RegionOperation 方向不一致（期望 {operation.direction}）；核对该方向的区块操作，缺少时先补清单。")
                if action.operation_ref != task.operation_id:
                    focus_operation = self.ledger.operations.get(
                        task.operation_id)
                    same_canonical = bool(
                        focus_operation is not None
                        and focus_operation.canonical_operation_id
                        and operation.canonical_operation_id
                        == focus_operation.canonical_operation_id)
                    if (same_canonical
                            and self.ledger.current_state_id
                            not in task_source_states(self.ledger, task)
                            and operation.status not in OPEN_OPERATION_STATES
                            and current_operation_binding(
                                self.ledger, task.operation_id) is not operation):
                        return (
                            f"当前 State 中的同类 Operation "
                            f"{action.operation_ref} 已经结束，不能完成当前焦点 "
                            f"{task.operation_id}。请先导航到该焦点的来源 State。"
                        )
                    previous = next((
                        attempt
                        for attempt in reversed(list(
                            self.ledger.attempts.values()))
                        if attempt.task_id == task.task_id
                    ), None)
                    if (previous is not None
                            and self._near_repeated_detour(previous, action)
                            and previous.source_state_id
                            == previous.target_state_id
                            and previous.outcome in {
                                "no_effect", "uncertain"}):
                        return (
                            "同一前置 owner 已在当前 Focus 中执行但没有产生 State "
                            "进展，不能立即原样重复。请改用其他当前可见 owner、"
                            "恢复动作，或继续目标 Operation。"
                        )
                return ""
            operation = (current_operation_binding(self.ledger, task.operation_id)
                         or self.ledger.operations.get(task.operation_id))
            if (action.purpose == "execute" and operation is not None
                    and operation.status == "deferred"):
                return (
                    "当前 Operation binding 仍为 deferred，不能只凭历史 operation_ref 执行；"
                    "请先核对当前可见控件的可用条件，再使用实际 action.owner_ref，或继续其他可用操作。")
            source_states = {
                self.ledger.occurrences[oid].state_id
                for oid in (operation.source_occurrence_ids if operation else [])
            }
            if (action.purpose == "route"
                    and self.ledger.current_state_id in source_states
                    and operation is not None
                    and action.kind == operation.action
                    and (action.operation_ref == task.operation_id
                         or action.target == operation.target)):
                return (
                    f"当前已在操作 {task.operation_id} 的来源状态；若正在执行派发的"
                    f"“{operation.action} {operation.target}”，请使用 "
                    f"action.owner_ref={operation.element_id or operation.region_id}。"
                    "不要填写内部 purpose/operation_ref，框架会根据 owner 绑定；坐标仍须依据最新截图。"
                )
            if action.purpose == "execute" and action.operation_ref != task.operation_id:
                operation_text = (
                    f"{operation.action} {operation.target}"
                    if operation is not None else task.operation_id
                )
                return (
                    f"当前任务 {task.operation_id}（{operation_text}）仍未结束，"
                    f"本轮却提交 {action.operation_ref or '空值'}。"
                    "请移除内部 purpose/operation_ref，改用当前真实动作对象的 action.owner_ref；"
                    "前置动作不等于目标任务已完成，是否完成由真实结果结算。"
                )
            if action.purpose == "execute":
                if operation is not None and action.kind != operation.action:
                    return (
                        f"当前任务只验证“{operation.action} "
                        f"{operation.target}”，不能用 {action.kind} 替换。"
                        f"若目标仍成立，请提交 kind={operation.action}、"
                        f"action.owner_ref={operation.element_id or operation.region_id}；"
                        "不要填写内部 purpose/operation_ref。若实际是另一控件或操作，先修正清单，不能伪报完成。"
                    )
                if (operation is not None
                        and operation.scope == "region"
                        and operation.direction
                        and action.direction != operation.direction):
                    return (
                        f"当前 RegionOperation 只验证 direction="
                        f"{operation.direction}，不能改为 "
                        f"{action.direction or '空值'}。请按登记方向执行，或在"
                        "最新截图显示需要另一方向时，先补充该区块对应方向的操作，再引用该区块执行。"
                    )
                if self.ledger.current_state_id not in source_states:
                    return (
                        "当前 State 没有该任务可执行的本地 Operation binding；"
                        "请用当前可见且已登记的 action.owner_ref 逐步到达目标；不要填内部 purpose=route。"
                    )
        return ""

    def _execute(
        self,
        *,
        task: Optional[Task],
        action: ActionRequest,
        screenshot: bytes,
        agent_reason: str = "",
    ) -> Dict[str, Any]:
        if self.restored_delivery:
            raise ValueError('保存的投递帧只能结算，必须先重新观察现场。')
        primitive = to_primitive(
            action,
            screenshot=screenshot,
            platform=self.platform,
        )
        attempt_id = self.ledger.mint("attempt")
        task_id = task.task_id if task is not None else ""
        before_ref = self.artifacts.save_attempt_before(attempt_id, screenshot)
        attempt = ActionAttempt(
            attempt_id=attempt_id,
            task_id=task_id,
            source_state_id=self.ledger.current_state_id,
            purpose=action.purpose,
            action=action_dict(action),
            before_ref=before_ref,
            agent_reason=agent_reason,
        )
        if action.kind == "click" and action.point_1000 is not None:
            captured = capture_click_anchor(screenshot, action.point_1000)
            if captured is not None:
                attempt.anchor_ref = self.artifacts.save_attempt_anchor(
                    attempt_id, captured.png)
                attempt.anchor_offset_px = list(captured.click_offset_px)
        self.ledger.attempts[attempt_id] = attempt
        if task is not None:
            task.attempt_count += 1
        if action.operation_ref:
            operation = self.ledger.operations.get(action.operation_ref)
            if operation is not None:
                if (task is not None
                        and action.operation_ref == task.operation_id
                        and operation.status in {
                            "pending", "active", "deferred", "failed"
                        }):
                    operation.status = "active"
                operation.attempt_count += 1
        self.ledger.event(
            "action_executed",
            attempt_id=attempt_id,
            task_id=task_id,
            action=attempt.action,
            before_ref=before_ref,
        )
        from .actions import execute_action
        observation = execute_action(
            self.env, action, screenshot=screenshot, platform=self.platform,
            pause=1.0 if primitive is None else 2.0)
        self.pending_action_error = str(
            (observation or {}).get("action_error") or "")
        self.actions_used += 1
        self.pending_attempt_id = attempt_id
        self.pending_before = screenshot
        if self.correction:
            self.ledger.event('correction_superseded_by_delivery', attempt_id=attempt_id,
                prior_correction=self.correction, next_step='settle actual delivered action; do not replay rejected proposal')
        self.correction = ""
        self.pending_report_correction = {}
        after = (observation or {}).get('screenshot')
        if isinstance(after, bytes) and after:
            attempt.after_ref = self.artifacts.save_attempt_after(attempt_id, after)
            self.ledger.event('action_delivery_returned', attempt_id=attempt_id,
                action=attempt.action, before_ref=before_ref, after_ref=attempt.after_ref,
                before_sha256=hashlib.sha256(screenshot).hexdigest(),
                after_sha256=hashlib.sha256(after).hexdigest(), action_error=self.pending_action_error,
                scope=self.scope.check())
        self.confirmed_state_id = ""
        self.confirmed_screenshot = b""
        return observation or {}

    def run(self, initial_observation: Dict[str, Any]) -> ExplorationResult:
        from .knowledge_retrieval import ContextBudgetExceeded
        observation = dict(initial_observation or {})
        stop_reason = "model_turn_limit"
        while self.model_turns < self.max_turns:
            if getattr(self, "report_correction_stop_reason", ""):
                stop_reason = self.report_correction_stop_reason
                break
            if self.taskless_recovery_error:
                stop_reason = "recovery_no_effect_budget_exhausted"
                break
            if self.restored_delivery:
                if self.pending_attempt_id:
                    observation = {'screenshot': self.restored_delivery[2]}
                else:
                    self.restored_delivery = None
                    prepare_resume_region_rediscovery(self.ledger)
                    self.resume_region_rediscovery_required = True
                    self.confirmed_state_id = ''
                    self.confirmed_screenshot = b''
                    observation = self.env._get_obs() or {}
            if (self.actions_used >= self.max_actions
                    and not self.pending_attempt_id
                    and self.ledger.states):
                stop_reason = "action_limit"
                break
            screenshot = observation.get("screenshot")
            if not isinstance(screenshot, (bytes, bytearray)) or not screenshot:
                stop_reason = "screenshot_unavailable"
                break
            screenshot = bytes(screenshot)
            frame_ref = self.artifacts.save_frame(screenshot)
            system_scope = self.scope.check()
            if self.restored_delivery:
                system_scope = 'target'
            if system_scope == "target":
                self.external_recovery_attempts = 0
            if system_scope == "external" and not self.pending_attempt_id:
                if (self.external_recovery_attempts
                        >= MAX_EXTERNAL_RECOVERY_ATTEMPTS):
                    stop_reason = "scope_recovery_exhausted"
                    self.ledger.event(
                        "external_surface_recovery_exhausted",
                        attempts=self.external_recovery_attempts,
                        reason=self.scope.last_reason,
                        screenshot_ref=frame_ref,
                    )
                    self.artifacts.checkpoint(self.ledger)
                    break
                self.external_recovery_attempts += 1
                self.ledger.event(
                    "external_surface_recovered",
                    reason=self.scope.last_reason,
                    screenshot_ref=frame_ref,
                    attempt=self.external_recovery_attempts,
                )
                observation = self.scope.recover() or {}
                self.artifacts.checkpoint(self.ledger)
                continue

            completion_observation = False
            task = (self.scheduler.choose(self.ledger, automatic_operation_selection=False)
                    if self.exploration_goal else self.scheduler.choose(self.ledger))
            if (task is None and not self.pending_attempt_id
                    and self.ledger.current_state_id
                    and not self.resume_region_rediscovery_required
                    and not self.exploration_goal):
                stop_reason = self._completion_reason(system_scope, screenshot)
                if self._report_budget().count >= self._report_budget().limit:
                    stop_reason = 'report_correction_exhausted'
                    break
                if (stop_reason != 'foreground_inventory_unconfirmed'
                        or system_scope != 'target'
                        or not self.ledger.state_occurrences(self.ledger.current_state_id)):
                    break
                # A fresh frame is not a failed inventory. Return to the
                # existing observation path before deciding there is no work.
                self.confirmed_state_id = ''
                self.confirmed_screenshot = b''
                completion_observation = True
                if not self._report_budget().count:
                    self.correction = (
                        '当前没有可选任务，但最新画面尚未确认。先识别当前可交互前景；'
                        '若仍为已清点的已知页面且无新内容，page_report=null；'
                        '出现新页面、弹层或缺失控件时只补必要清单。'
                        '未解决的任务仍保留，不重放旧动作，不因无任务宣称应用完整。')
                self.last_context_task_id = None
                self.ledger.event('completion_observation_required',
                    state_ref=self.ledger.current_state_id, screenshot_ref=frame_ref,
                    reason='Latest target-app frame needs observation before completion decision')
            if (task is not None and not self.pending_attempt_id
                    and not 0 < self._report_budget().count < self._report_budget().limit):
                replay_action = self._visual_anchor_route_action(
                    task=task,
                    screenshot=screenshot,
                )
                if replay_action is not None and self.actions_used < self.max_actions:
                    observation = self._execute(
                        task=task,
                        action=replay_action,
                        screenshot=screenshot,
                    )
                    self.artifacts.checkpoint(self.ledger)
                    continue
            screenshots = (
                [self.pending_before, screenshot]
                if self.pending_attempt_id else [screenshot]
            )
            retained_partition_screen = self._partition_screen_for_frame(screenshot)
            repair_base = getattr(self, "report_repair_base", None)
            from .contracts import submission_contract
            self.current_submission = submission_contract(self.pending_attempt_id,
                edits=retained_partition_screen is not None and repair_base is not None,
                correction_field=self.pending_report_correction.get('field_path', ''))
            try:
                context = self._context(task, system_scope)
                self.offered_action_candidate = (None if self.current_submission['phase'] == 'inventory_edits'
                    else self._known_action_candidate(task, screenshot))
                if self.offered_action_candidate:
                    candidate = self.offered_action_candidate
                    context['当前动作候选'] = {'protocol': 'owner_confirmation.v1',
                        **{key: candidate[key] for key in ('kind', 'target', 'direction')},
                        'instruction': '仅在当前图确认此目标匹配且安全可定位时，action.owner_ref填@current并原样使用kind/target/direction，填写当前视觉落点。'
                            '框架生成内部绑定，不需抄其他ID。不匹配则不用@current；action=null说明缺口，或沿原路径明确选择其他owner。'}
            except ContextBudgetExceeded as exc:
                self.ledger.event("context_budget_exceeded", reason=str(exc), screenshot_ref=frame_ref)
                stop_reason = "context_budget_exceeded"
                break
            retained_partition_screen = self._partition_screen_for_frame(screenshot)
            if retained_partition_screen is not None:
                context["保留的合法位置提议"] = {
                    "screen": asdict(retained_partition_screen),
                    "instruction": "同一截图的结构合法位置提议，仅暂存，尚未发布；提交方式见本轮提交合同。"}
            repair_base = getattr(self, "report_repair_base", None)
            if retained_partition_screen is not None and repair_base is not None:
                from .report_edits import repair_preview
                context["清单增量纠正"] = {
                    **repair_preview(repair_base[2]),
                    'application_result': getattr(self, 'report_edit_application', '候选仅暂存，未发布'),
                    "instruction": "仅提交page_report_edits；未列内容由框架保留。"
                                   "缺其他独立入口时，先核对原条目的name/observation/operations；"
                                   "原条目正确则保留并add缺项，不能把补缺项误作replace原条目。"
                                   "确实混写多个物理控件才拆分并保留各成员；原条目错误才有依据地replace/remove。"
                                   "是否已修以实际edits和修后清单为准，不以reason自述代替。"
                                   "路径基于这份候选的0起始index。新增控件用/regions/i/elements/-，"
                                   "删除数组项从大到小，新区块追加/regions/-。screen/previous_action/page_report/action=null；"
                                   "缓存回执不改，不能重做GUI。已知引用不变，新region_ref/element_ref留空。"}
                review_scope = self.partition_review_cache.get('scope', ())
                reviews = self.partition_review_cache.get('reviews', [])
                if (reviews and review_scope[:2] == (self.pending_attempt_id, hashlib.sha256(screenshot).hexdigest())
                        and reviews[-1].get('decision') in {'different', 'uncertain'}):
                    previous_review = reviews[-1]
                    context['上一轮清单审核'] = {
                        'decision': previous_review['decision'], 'reason': previous_review['reason'],
                        'application_state': self.report_edit_application,
                        'regions': [{'path': region['path'], 'name': region['name'],
                                     'parent_ref': region['parent_ref']}
                                    for region in previous_review['candidate']['regions']],
                        'instruction': '这是同帧/Attempt最近一次审核意见，不是程序认定的正确答案。'
                            '格式错误不会自动解决这份意见；据当前截图和候选核对。'
                            '这里的路径属于上次审核候选；已应用编辑后索引可能变化，'
                            '提交路径以当前清单增量纠正卡为准，修后仍需原审核。'}
                reviewer_error = self.partition_review_cache.get('reviewer_error')
                if reviewer_error:
                    context['Reviewer待核对意见'] = {
                        'status': '未经确认的诊断线索，不是准入判决',
                        'contract_error': reviewer_error['error'],
                        'reason': self.partition_review_cache.get('result', {}).get('reason', ''),
                        'application_state': self.report_edit_application,
                        'instruction': '据当前图核对意见，仅按本轮edits合同修改；修后仍需原审核。'}
                card = context.get('合同纠正卡')
                if card:
                    card = dict(card)
                    card['required_change'] = self.current_submission['instruction']
                    card['application_state'] = getattr(self, 'report_edit_application', '候选仅暂存，未发布')
                    context['合同纠正卡'] = card
            retained_inventory = self._effect_inventory_for_frame(screenshot)
            if retained_inventory is not None:
                context["保留的已校验清单"] = {
                    "screen": asdict(retained_inventory.screen),
                    "regions": [{"report_index": index, "region_ref": region.region_ref, "name": region.name}
                                for index, region in enumerate(retained_inventory.page_report.regions)],
                    "instruction": "同一动作和后帧的清单已通过结构与Element校验，尚待最终Region身份处理。"
                                   "只修previous_action.region_effects，当前清单项用上述report_index引用；"
                                   "page_report留空，位置和清单由框架保留。若确需重判这份观察，报告screen.identity=uncertain。",
                }
            correction_only_turn = "合同纠正卡" in context
            if self.correction and 0 < self._report_budget().count < self._report_budget().limit:
                self.ledger.event("report_correction_delivered", recipient="main_agent",
                                  round=self._report_budget().count + 1,
                                  required_change=self.correction)
            try:
                turn = self.agent.decide(
                    context=context,
                    screenshots=screenshots,
                    has_pending_action=bool(self.pending_attempt_id),
                    pending_attempt_id=self.pending_attempt_id,
                    corrections=self._report_budget(),
                )
            except ContextBudgetExceeded as exc:
                self.ledger.event("context_budget_exceeded", reason=str(exc), screenshot_ref=frame_ref)
                stop_reason = "context_budget_exceeded"
                break
            except (TypeError, ValueError) as exc:
                if self._handle_agent_decide_failure(
                        task=task,
                        error=exc,
                        screenshot=screenshot,
                        frame_ref=frame_ref,
                ):
                    self.model_turns += 1
                    self.artifacts.checkpoint(self.ledger)
                    continue
                self.correction = str(exc)[:500]
                self.model_turns += 1
                self.artifacts.checkpoint(self.ledger)
                continue
            self.model_turns += 1
            if (self.current_submission['phase'] == 'inventory_edits'
                    and turn.page_report_edits is None and turn.screen is None):
                self.retained_partition_screen = None
                self.report_repair_base = None
                self.pending_report_correction = {}
                self.correction = '已退出缓存编辑，候选未发布；重新观察并提交位置及真实动作回执，不重做GUI。'
                self.ledger.event('report_edits_abandoned', reason=turn.reason, pending_attempt_id=self.pending_attempt_id)
                self.artifacts.checkpoint(self.ledger)
                continue
            partition_edits = []
            if turn.page_report_edits is not None:
                try:
                    turn = self._materialize_report_edits(turn, screenshot, frame_ref, edit_trace=partition_edits)
                except (TypeError, ValueError) as exc:
                    error = SettlementContractError(code="PAGE_REPORT_EDIT_INVALID", field_path="page_report_edits",
                        expected="valid same-frame page_report_edits", received=str(exc), message="修正增量清单字段；缓存提议未发布")
                    error.edit_application = getattr(exc, 'edit_application', '整批编辑未应用，缓存候选未变化')
                    self._handle_agent_decide_failure(task=task, error=error, screenshot=screenshot, frame_ref=frame_ref)
                    self.artifacts.checkpoint(self.ledger)
                    continue
            if correction_only_turn:
                turn = replace(
                    turn,
                    action=None,
                    current_task_result="",
                    representative_probe=None,
                    next_operation_ref="",
                )
            if retained_partition_screen is not None:
                if turn.app_scope == "target_app" and turn.screen is not None and turn.screen.identity != "uncertain":
                    self.ledger.event("partition_correction_screen_retained",
                        proposed_screen=asdict(turn.screen), retained_screen=asdict(retained_partition_screen))
                    turn = replace(turn, screen=retained_partition_screen)
                else:
                    self.retained_partition_screen = None
            if retained_inventory is not None:
                if turn.app_scope == "target_app" and turn.screen is not None and turn.screen.identity != "uncertain":
                    self.ledger.event("validated_pending_inventory_retained", attempt_id=self.pending_attempt_id,
                        ignored_report=asdict(turn.page_report) if turn.page_report else None)
                    turn = replace(turn, screen=retained_inventory.screen, page_report=retained_inventory.page_report)
                else:
                    self.retained_effect_inventory = None
            if task is not None:
                task.strategy = turn.strategy

            if system_scope == "target" and turn.app_scope == "external_app":
                self.model_scope_conflicts += 1
                self.ledger.event(
                    "model_external_scope_conflict_rejected",
                    conflict_count=self.model_scope_conflicts,
                    reason=self.scope.last_reason,
                    screenshot_ref=frame_ref,
                )
                if self.model_scope_conflicts >= 3:
                    stop_reason = "model_scope_conflict_exhausted"
                    self.artifacts.checkpoint(self.ledger)
                    break
                self.correction = (
                    "app_scope 与系统窗口归属冲突：系统确认目标应用在前台，本轮应填 target_app。"
                    "这不证明所有可见浮层都属于目标应用；若截图有无关通知或遮挡，"
                    "先用安全恢复动作清理，page_report=null，不要将无关浮层登记为应用区块。"
                )
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue
            self.model_scope_conflicts = 0
            if turn.context_query and system_scope != "external" and turn.app_scope == "target_app":
                try:
                    self._request_context_lookup(turn, frame_ref=frame_ref)
                except ContextLookupExhausted as exc:
                    self.ledger.event("context_lookup_exhausted", reason=str(exc), screenshot_ref=frame_ref)
                    if self._handle_context_lookup_exhaustion(task, reason=str(exc), frame_ref=frame_ref):
                        self.artifacts.checkpoint(self.ledger)
                        observation = self.env._get_obs() or observation
                        continue
                    stop_reason = "context_lookup_exhausted"
                    break
                except ValueError as exc:
                    self.ledger.event('context_lookup_invalid', reason=str(exc), screenshot_ref=frame_ref)
                    self._record_action_rejection(task, str(exc))
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue
            if system_scope == "external" or turn.app_scope == "external_app":
                if self.restored_delivery:
                    stop_reason = 'restored_delivery_scope_unconfirmed'
                    break
                try:
                    self._settle_pending(
                        turn, screenshot=screenshot, frame_ref=frame_ref)
                except ValueError as exc:
                    self._handle_pending_report_rejection(
                        turn=turn,
                        task=task,
                        error=exc,
                        screenshot=screenshot,
                        frame_ref=frame_ref,
                    )
                self.ledger.event(
                    "model_reported_external_surface",
                    reason=(self.scope.last_reason
                            if system_scope == "external" else turn.reason),
                    screenshot_ref=frame_ref,
                )
                if self.taskless_recovery_error:
                    stop_reason = "recovery_no_effect_budget_exhausted"
                    break
                observation = self.scope.recover() or {}
                self.correction = (
                    "系统已确认上一画面属于外部应用；已尝试恢复目标应用，"
                    "外部画面没有登记为 Page/State，请重新识别当前画面"
                )
                self.artifacts.checkpoint(self.ledger)
                continue
            if (turn.app_scope != "target_app"
                    or (turn.screen is None and turn.region_refinement is None)):
                self.correction = (
                    "当前系统归属不能直接证明目标应用；请根据截图明确 target_app 或 "
                    "external_app。uncertain 不能登记页面或执行动作。"
                )
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue

            if (self.pending_attempt_id
                    and turn.previous_action is not None
                    and self.pending_action_error):
                attempt_id = self.pending_attempt_id
                delivery_error = self.pending_action_error
                safe_turn = replace(
                    turn,
                    page_report=None,
                    action=None,
                    current_task_result="",
                )
                self._settle_pending(
                    safe_turn,
                    screenshot=screenshot,
                    frame_ref=frame_ref,
                )
                self.ledger.event(
                    "action_delivery_error_landing_quarantined",
                    attempt_id=attempt_id,
                    error=delivery_error,
                    inventory_quarantined=True,
                )
                self.correction = (
                    f"动作投递返回 {delivery_error}；框架已把本次结算为 "
                    "no_effect/retry，并隔离异常 landing 的 page_report 和"
                    "同轮 action，未登记新 State。请基于 fresh screenshot 先"
                    "恢复到来源状态；输入动作只有在目标字段获得真实编辑焦点"
                    "后才能重试。"
                )
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue

            if turn.region_refinement is not None:
                try:
                    self._apply_region_refinement(turn, screenshot=screenshot, frame_ref=frame_ref)
                except (OSError, TypeError, ValueError) as exc:
                    self.ledger.event("region_refinement_rejected", proposal=turn.region_refinement,
                                      reason=str(exc), screenshot_ref=frame_ref)
                    self._reject_observation_report(self.ledger, turn, task, exc,
                                                    screenshot=screenshot, frame_ref=frame_ref)
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue

            try:
                from .inventory import validate_report_structure
                if turn.page_report is not None:
                    validate_report_structure(turn.page_report)
            except (TypeError, ValueError) as exc:
                self._reject_observation_report(self.ledger, turn, task, exc,
                    screenshot=screenshot, frame_ref=frame_ref)
                self.ledger.event("page_report_structure_rejected", reason=str(exc), screenshot_ref=frame_ref)
                self.artifacts.checkpoint(self.ledger)
                continue

            try:
                from .state_review import verify_known_state
                self.known_state_review_key = verify_known_state(
                    self.ledger, self.agent, self.artifacts, screen=turn.screen,
                    screenshot=screenshot, frame_ref=frame_ref,
                    approved_key=getattr(self, "known_state_review_key", ()))
            except (OSError, TypeError, ValueError) as exc:
                self.ledger.event("known_state_visual_reuse_rejected",
                    state_ref=turn.screen.state_ref, screenshot_ref=frame_ref, reason=str(exc))
                self._reject_observation_report(self.ledger, turn, task, exc,
                    screenshot=screenshot, frame_ref=frame_ref)
                self.artifacts.checkpoint(self.ledger)
                continue

            try:
                from .partition_review import verify_partition, qualification_gaps, validate_qualification_dependencies
                if not hasattr(self, "partition_review_cache"):
                    self.partition_review_cache = {}
                repair_base = getattr(self, "report_repair_base", None)
                active_qualification_gaps = qualification_gaps(self.ledger)
                inventory_gaps = deferred_inventory_reports(self.ledger)
                partition_reason = None if getattr(self, "defer_partition_review", False) else verify_partition(self.agent, report=turn.page_report,
                    screenshot=screenshot, cache=self.partition_review_cache,
                    attempt_ref=self.pending_attempt_id, edit_trace=partition_edits,
                    force=bool(active_qualification_gaps or inventory_gaps) or repair_base is not None and repair_base[:2] == (self.pending_attempt_id, screenshot),
                    gaps=active_qualification_gaps, inventory_gaps=inventory_gaps,
                    run_scope=self._partition_scope(turn.page_report, context), corrections=self._report_budget())
                qualification_review = self.partition_review_cache.get('qualification') if partition_reason else None
                if qualification_review:
                    validate_qualification_dependencies(
                        turn.page_report, qualification_review, self.ledger,
                        turn.previous_action, current_screen=turn.screen)
                    self.ledger.event('partition_qualification_reviewed', screenshot_ref=frame_ref,
                        attempt_ref=self.pending_attempt_id, review=qualification_review)
                if partition_reason:
                    self.pending_report_correction.pop('unresolved_inventory', None)
                    self.retained_partition_screen = None
                    self.ledger.event("partition_partially_admitted" if qualification_review and qualification_review['decision'] == 'different' else "partition_visually_confirmed",
                        screenshot_ref=frame_ref, reason=partition_reason)
            except (OSError, TypeError, ValueError) as exc:
                if getattr(exc, 'recipient', '') == 'partition_reviewer':
                    self._end_report_corrections(turn, task, exc, frame_ref=frame_ref)
                    self.artifacts.checkpoint(self.ledger)
                    continue
                if bind_screen(self.ledger, turn.screen, screenshot_ref=frame_ref).ok:
                    self.retained_partition_screen = (self.pending_attempt_id, screenshot, turn.screen)
                self.ledger.event("partition_visual_review_rejected",
                    screenshot_ref=frame_ref, reason=str(exc))
                self._reject_observation_report(self.ledger, turn, task, exc,
                    screenshot=screenshot, frame_ref=frame_ref)
                self.artifacts.checkpoint(self.ledger)
                continue

            unobserved_state_switch = bool(
                not self.pending_attempt_id and self.ledger.current_state_id
                and turn.screen.state_ref in self.ledger.states
                and turn.screen.state_ref != self.ledger.current_state_id)
            if ((self.resume_region_rediscovery_required and turn.page_report is not None)
                    or unobserved_state_switch):
                try:
                    validate_state_composition(self.ledger, turn.screen, turn.page_report)
                except SettlementContractError as exc:
                    self.ledger.event("state_composition_rejected", error_code=exc.code,
                        previous_state_ref=self.ledger.current_state_id,
                        state_ref=turn.screen.state_ref, screenshot_ref=frame_ref)
                    self._reject_observation_report(self.ledger, turn, task, exc,
                        screenshot=screenshot, frame_ref=frame_ref)
                    self.artifacts.checkpoint(self.ledger)
                    continue
            location = bind_screen(
                self.ledger,
                turn.screen,
                screenshot_ref=frame_ref,
            )
            if not location.ok:
                if (turn.screen.identity != "uncertain" or self._report_budget().count
                        or completion_observation):
                    self._reject_observation_report(
                        self.ledger, turn, task,
                        SettlementContractError(code="LOCATION_REPORT_INVALID", field_path="screen",
                            expected="与最新截图一致的有效Page/State引用", received=location.issue,
                            message=location.issue), screenshot=screenshot, frame_ref=frame_ref)
                    self.artifacts.checkpoint(self.ledger)
                    continue
                self.correction = location.issue
                if turn.screen.identity == "uncertain":
                    self.correction = (
                        "当前落点尚未确定，下一轮使用新截图继续观察；只有新图支持时才"
                        "报告 known/new，未稳定时可保持 uncertain。不得重复原动作。"
                    )
                if self.pending_attempt_id:
                    attempt = self.ledger.attempts[self.pending_attempt_id]
                    attempt.after_ref = self.artifacts.save_attempt_after(
                        attempt.attempt_id, screenshot)
                if turn.action is not None and turn.action.kind == "wait":
                    time.sleep(1.0)
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or {}
                continue
            previous_state = self.ledger.states.get(
                self.ledger.current_state_id)
            created_state = location.ledger.states.get(location.state_id)
            current_survey = self.ledger.survey_task(
                self.ledger.current_state_id)
            natural_same_page_state = bool(
                location.created_state
                and previous_state
                and created_state
                and created_state.page_id == previous_state.page_id
                and turn.page_report is not None
            )
            if (location.created_state
                    and self.ledger.current_state_id
                    and not self.pending_attempt_id
                    and not natural_same_page_state):
                self.correction = (
                    "当前没有待结算动作，不能把预期结果提前登记为新 Page/State；"
                    "同一 Page 若自然出现了新的可见结构，可提交该新 State "
                    "及完整 page_report；否则请先执行动作，再根据真实结果新建。"
                )
                self.artifacts.checkpoint(self.ledger)
                continue
            report_baseline = self.ledger
            budget = self._report_budget()
            if budget.count >= budget.limit and turn.page_report is not None:
                changed_state = bool(
                    self.pending_attempt_id and location.state_id != self.blocked_report_state
                    and (visible_change_ratio(self.pending_before, screenshot) or 0) > UNCHANGED_FRAME_RATIO)
                if changed_state:
                    budget.reset()
                    self.blocked_report_state = ""
                else:
                    self.report_correction_stop_reason = "report_correction_exhausted"
                    self.artifacts.checkpoint(self.ledger)
                    continue
            if (budget.required_report and budget.count < budget.limit
                    and turn.page_report is None):
                self._reject_observation_report(
                    report_baseline, turn, task,
                    SettlementContractError(code="REPORT_CORRECTION_REQUIRED", field_path="page_report",
                        expected="修正被拒绝的清单", received="null",
                        message="清单冲突尚未解决，不能省略page_report直接执行动作；请修正具体候选。"),
                    screenshot=screenshot, frame_ref=frame_ref)
                self.artifacts.checkpoint(self.ledger)
                continue
            # bind_screen already cloned the ledger. Do not checkpoint this
            # candidate or release pending until its submitted inventory passes.
            self.ledger = location.ledger
            if (natural_same_page_state
                    and current_survey is not None
                    and current_survey.status in {"pending", "active"}):
                superseded = self.ledger.tasks[current_survey.task_id]
                superseded.status = "cancelled"
                superseded.reason = (
                    "同一页面在清点期间自然进入了新的可见结构，旧状态清点已被替代。"
                )
                self.ledger.event(
                    "survey_superseded_by_natural_state",
                    task_id=superseded.task_id,
                    source_state_id=previous_state.state_id,
                    target_state_id=location.state_id,
                )
            try:
                self._settle_pending(
                    turn, screenshot=screenshot, frame_ref=frame_ref, finalize=False)
            except ValueError as exc:
                self._reject_observation_report(
                    report_baseline, turn, task, exc,
                    screenshot=screenshot,
                    frame_ref=frame_ref,
                )
                self.artifacts.checkpoint(self.ledger)
                continue
            if self.pending_attempt_id:
                report_baseline.attempts[self.pending_attempt_id].after_ref = (
                    self.ledger.attempts[self.pending_attempt_id].after_ref)
            page_report = turn.page_report
            if page_report is not None and qualification_review:
                from .partition_review import qualification_report
                page_report = qualification_report(page_report, qualification_review)
            rediscovering = getattr(
                self, "resume_region_rediscovery_required", False)
            if (rediscovering and page_report is not None and not location.created_state
                    and not active_qualification_gaps and not qualification_review
                    and self.ledger.states[location.state_id].survey_complete
                    and any(r.elements or r.region_operations for r in page_report.regions)):
                from .inventory import resume_binding_updates
                filtered_report = resume_binding_updates(self.ledger, location.state_id, page_report)
                retained_refs = [operation.operation_ref for region in filtered_report.regions
                    for element in region.elements for operation in element.operations]
                self.ledger.event("resume_known_state_bindings_reassessed" if retained_refs
                    else "resume_known_state_inventory_ignored", state_id=location.state_id,
                    screenshot_ref=frame_ref,
                    unrequested_regions=[asdict(r) for r in page_report.regions
                                         if r.elements or r.region_operations],
                    retained_operation_refs=retained_refs,
                    reason="Known State reuses controls; only explicit unattempted recorded-binding eligibility updates are retained.")
                page_report = filtered_report
                turn = replace(turn, page_report=page_report)
            inventory_before = (
                self._inventory_facts() if page_report is not None else {})
            if (page_report is not None
                    and task is not None
                    and task.kind == "survey_page"
                    and self.ledger.current_state_id != task.state_id
                    and not natural_same_page_state
                    and not rediscovering):
                self.correction = (
                    f"当前任务要清点 {task.state_id}，但当前位置是 "
                    f"{self.ledger.current_state_id}；不能用当前位置的重复清单结算"
                    "另一个状态。请令 page_report=null，并用当前可见 owner 逐步"
                    "返回来源状态。"
                )
                self.ledger = report_baseline
                self.ledger.event(
                    "survey_report_wrong_state_rejected",
                    task_id=task.task_id,
                    source_state_id=task.state_id,
                    current_state_id=location.state_id,
                )
                self.artifacts.checkpoint(self.ledger)
                continue
            first_inventory_report = bool(
                page_report is not None
                and not any(
                    event["kind"] == "page_inventory_recorded"
                    and event["payload"].get("state_id")
                    == self.ledger.current_state_id
                    for event in self.ledger.events
                )
            )
            if page_report is not None:
                current_region_ids = {
                    item.region_id for item in self.ledger.state_occurrences(
                        self.ledger.current_state_id)}
                suggested_region_ids = [
                    item.region_ref for item in page_report.regions
                    if item.region_ref in self.ledger.regions
                    and item.region_ref not in current_region_ids
                ]
                page_report = self._normalize_page_report_refs_for_state(
                    report=page_report,
                    state_id=self.ledger.current_state_id,
                    screen_identity=turn.screen.identity,
                )
                try:
                    page_report = review_page_report_element_candidates(
                        self.ledger, self.agent,
                        report=page_report,
                        state_id=self.ledger.current_state_id,
                        screenshot=screenshot,
                        corrections=budget,
                    )
                except OSError as exc:
                    self.ledger = report_baseline
                    if self.pending_attempt_id:
                        self.ledger.attempts[self.pending_attempt_id].after_ref = self.artifacts.save_attempt_after(
                            self.pending_attempt_id, screenshot)
                    self.ledger.event("report_evidence_unavailable", screenshot_ref=frame_ref,
                                      reason=str(exc), candidate_report=asdict(page_report))
                    self.report_correction_stop_reason = "report_evidence_unavailable"
                    self.artifacts.checkpoint(self.ledger)
                    continue
                except (TypeError, ValueError) as exc:
                    self._reject_observation_report(
                        report_baseline, turn, task,
                        exc if isinstance(exc, SettlementContractError) else SettlementContractError(
                            code="PAGE_REPORT_INVALID",
                            field_path="page_report.regions[].elements",
                            expected="resolved Element refs in the current Variant",
                            received=str(exc)[:500], message=str(exc)[:500],
                        ),
                        screenshot=screenshot, frame_ref=frame_ref,
                    )
                    self.ledger.event(
                        ("page_report_precheck_rejected" if isinstance(exc, SettlementContractError)
                         else "element_identity_batch_unresolved"),
                        state_id=location.state_id,
                        reason=self.correction,
                    )
                    self.artifacts.checkpoint(self.ledger)
                    continue
                inventory = apply_page_report(
                    self.ledger,
                    state_id=self.ledger.current_state_id,
                    report=page_report,
                    screenshot_ref=frame_ref,
                    qualification_review=qualification_review,
                )
                if not inventory.ok:
                    self._reject_observation_report(
                        report_baseline, turn, task,
                        SettlementContractError(
                            code="PAGE_REPORT_INVALID", field_path="page_report",
                            expected="valid current-State inventory",
                            received=inventory.issue, message=inventory.issue,
                        ),
                        screenshot=screenshot, frame_ref=frame_ref,
                    )
                    self.artifacts.checkpoint(self.ledger)
                    continue
                self.ledger = inventory.ledger
                if (getattr(self, "defer_partition_review", False)
                        and page_report.regions):
                    self.ledger.event("partition_review_deferred",
                        state_id=self.ledger.current_state_id, screenshot_ref=frame_ref,
                        region_ids=list(inventory.reported_region_ids),
                        reason="Inventory references accepted; visual partition quality remains unreviewed.")
                self.ledger.event(
                    "region_review_observed",
                    state_id=self.ledger.current_state_id,
                    new_region_ids=list(inventory.new_region_ids),
                    observed_operations=inventory.observed_operations,
                    screenshot_ref=frame_ref,
                    source_attempt_ref=(turn.previous_action.attempt_ref
                                        if turn.previous_action is not None else ""),
                    suggested_region_ids=suggested_region_ids,
                )

            if (self.pending_attempt_id and turn.previous_action is not None
                    and turn.previous_action.region_effects is not None):
                try:
                    record_region_effects(
                        self.ledger, self.pending_attempt_id,
                        turn.previous_action.region_effects,
                        inventory.reported_region_ids if page_report is not None else (),
                        region_hints={reported.region_ref: assigned for reported, assigned in zip(
                            turn.page_report.regions, inventory.reported_region_ids) if reported.region_ref}
                        if turn.page_report is not None else {},
                    )
                except (TypeError, ValueError) as exc:
                    if page_report is not None:
                        self.retained_effect_inventory = (self.pending_attempt_id, screenshot, turn)
                    self._reject_observation_report(
                        report_baseline, turn, task,
                        SettlementContractError(
                            code="REGION_EFFECT_INVALID", field_path="previous_action.region_effects",
                            expected="before refs or current page_report indices with explicit cause",
                            received=str(exc), message=str(exc)),
                        screenshot=screenshot, frame_ref=frame_ref)
                    self.artifacts.checkpoint(self.ledger)
                    continue
            isolated_result = self._finish_pending_settlement(independent_known_landing=bool(
                system_scope == 'target' and turn.screen.identity == 'known'
                and page_report is None and not self.resume_region_rediscovery_required
                and not self.restored_delivery
                and self.ledger.state_occurrences(self.ledger.current_state_id)))
            if isolated_result:
                self.confirmed_state_id = self.ledger.current_state_id
                self.confirmed_screenshot = screenshot
                self._accept_report_corrections(interface_changed=False)
                self.correction = ('上一动作保留未知，相关任务已暂挂；不重放、不依赖其成功。'
                                   '按当前工作Region选择其他适用操作，无可做事项时按原规则带缺口换区。')
                self.last_context_task_id = None
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue
            if getattr(self, 'report_correction_stop_reason', ''):
                stop_reason = self.report_correction_stop_reason
                break
            if self.taskless_recovery_error:
                stop_reason = "recovery_no_effect_budget_exhausted"
                break
            if self.restart_recovery_task_id:
                observation = self._perform_requested_restart()
                self.artifacts.checkpoint(self.ledger)
                continue
            if (getattr(self, "resume_region_rediscovery_required", False)
                    and turn.page_report is None
                    and not (
                        turn.action is not None
                        and not turn.action.owner_ref
                        and not turn.action.operation_ref
                        and turn.action.kind != "scroll"
                    )):
                self.correction = (
                    "重启后请先根据最新截图提交目标或路线起点 Region 的 "
                    "page_report；不要求完整清点，也不要求恢复旧 Page/State。"
                    "确认当前区块和操作前，不能沿用旧位置执行或结束遍历。"
                )
                self.ledger.event(
                    "resume_region_rediscovery_report_required",
                    screenshot_ref=frame_ref,
                )
                self.artifacts.checkpoint(self.ledger)
                continue

            self.confirmed_state_id = self.ledger.current_state_id
            self.confirmed_screenshot = screenshot

            if page_report is not None:
                confirmed_state = self.ledger.states[
                    self.ledger.current_state_id]
                pending_reviews = pending_region_reviews(
                    self.ledger,
                    self.ledger.current_state_id)
                if pending_reviews and (confirmed_state.survey_complete or rediscovering):
                    hints = list(dict.fromkeys(
                        region_id
                        for record in pending_reviews.values()
                        for region_id in record["suggested_region_ids"]))
                    try:
                        self.ledger = review_region_identity(
                            self.ledger, self.agent, self.artifacts,
                            state_id=self.ledger.current_state_id,
                            current_region_ids=list(pending_reviews),
                            screenshot=screenshot,
                            suggested_region_ids=hints,
                            review_records=pending_reviews,
                            rediscovering=rediscovering,
                            corrections=budget,
                        )
                    except ReportCorrectionExhausted as exc:
                        self._end_report_corrections(turn, task, exc, frame_ref=frame_ref)
                        self.artifacts.checkpoint(self.ledger)
                        continue
                    except SettlementContractError as exc:
                        self.ledger.event("framework_record_error", error_code=exc.code,
                                          field_path=exc.field_path, reason=str(exc), screenshot_ref=frame_ref)
                        self.report_correction_stop_reason = "framework_record_error"
                        self.artifacts.checkpoint(self.ledger)
                        continue
                    self.ledger.event(
                        "region_review_batch_finished",
                        state_id=self.ledger.current_state_id,
                        region_ids=list(pending_reviews),
                    )
                if (page_report.survey_complete
                        and self.ledger.current_state_id in deferred_inventory_reports(self.ledger)
                        and not (qualification_review or {}).get('omission_checks')
                        and (deferred_inventory_reports(self.ledger)[self.ledger.current_state_id].get('issue_kind')
                             != 'independent_omission' or qualification_review and qualification_review['decision'] == 'same')):
                    self.ledger.event("inventory_report_resolved", state_id=self.ledger.current_state_id,
                                      screenshot_ref=frame_ref, reason="完整清点报告及身份审核已通过。")
                resumed_task = self.ledger.current_task()
                if rediscovering and page_report.regions:
                    self.resume_region_rediscovery_required = False
                    if resumed_task is not None:
                        resumed_task.strategy = ""
                    self.ledger.event(
                        "resume_region_rediscovery_completed",
                        state_id=self.ledger.current_state_id,
                        region_ids=[
                            item.region_id for item in self.ledger.state_occurrences(
                                self.ledger.current_state_id)
                        ],
                    )
                self._accept_report_corrections(interface_changed=bool(
                    turn.previous_action and self.ledger.current_state_id != self.blocked_report_state))
                region_survey_scroll = bool(
                    turn.action is not None
                    and turn.action.kind == "scroll"
                    and turn.action.owner_ref in self.ledger.regions
                    and not confirmed_state.survey_complete
                    and not first_inventory_report
                )
                if (turn.action is not None
                        and not region_survey_scroll
                        and (turn.action.owner_ref
                             or turn.action.purpose == "execute"
                             or turn.action.kind == "click")):
                    if turn.action.kind == "click" and not turn.action.owner_ref:
                        self.correction = (
                            "本次点击未执行：缺少 owner_ref。清单已保存；请先选择当前"
                            "页面其他已绑定、可执行的待办，用 next_operation_ref 改选，"
                            "并使用该控件的 owner_ref 点击。原操作保留，不记失败；"
                            "清点尚未完成时先补充所需观察。单独的恢复点击请令 page_report=null。"
                        )
                        # This feedback belongs to the saved page, not the old task
                        # that may just have completed during settlement.
                        self.last_context_task_id = None
                    elif confirmed_state.survey_complete:
                        self.correction = (
                            "页面清单已保存，但不能在提交 page_report 的同一轮"
                            "执行功能操作。请下一轮从当前页面卡片填写 owner_ref。"
                        )
                    else:
                        self.correction = (
                            "清单已保存，survey_complete=false 保持未完整。"
                            "本轮候选点击未执行；下一轮使用当前卡片的 owner_ref "
                            "调查缺失信息。无需为了放行点击把未完成的调查标为完整。"
                        )
                    self.last_context_task_id = None
                    self.ledger.event(
                        "same_turn_operation_rejected",
                        state_id=self.ledger.current_state_id,
                        owner_ref=turn.action.owner_ref,
                    )
                    self.artifacts.checkpoint(self.ledger)
                    continue
            if self.restored_delivery and not self.pending_attempt_id:
                self.artifacts.checkpoint(self.ledger)
                continue
            self._accept_report_corrections(interface_changed=bool(
                turn.previous_action and self.ledger.current_state_id != self.blocked_report_state))
            try:
                apply_representative_probe(self.ledger, task, turn)
            except ValueError as exc:
                self.correction = str(exc)[:500]
                self.ledger.event(
                    "representative_probe_rejected",
                    task_id=(task.task_id if task is not None else ""),
                    reason=self.correction,
                )
                self.artifacts.checkpoint(self.ledger)
                continue
            current_survey = self.ledger.survey_task(self.ledger.current_state_id)
            survey_observation = bool(
                turn.action is not None
                and (
                    bool(turn.action.owner_ref)
                    or ((not turn.action.purpose
                         or turn.action.purpose in {"survey", "recover"})
                        and turn.action.kind != "scroll"
                        and not turn.action.owner_ref)
                )
            )
            if (current_survey is not None
                    and current_survey.status in {"pending", "active"}
                    and page_report is None
                    and not survey_observation
                    and not self._current_region_route_ready(
                        self.ledger.current_task())):
                self.correction = (
                    "page_report 缺少本轮所需清点信息；请补充当前截图中的新事实，"
                    "或用已登记的 action.owner_ref 调查缺失信息。不要为了继续而虚报 survey_complete=true。"
                )
                self.artifacts.checkpoint(self.ledger)
                continue

            inventory_progress = bool(
                page_report is not None
                and (self._inventory_facts() != inventory_before
                     or (rediscovering
                         and not self.resume_region_rediscovery_required))
            )
            if (page_report is not None
                    and task is not None
                    and task.kind == "explore_operation"
                    and turn.previous_action is None
                    and turn.action is None
                    and not turn.current_task_result
                    and not inventory_progress):
                issue = (
                    f"Region {', '.join(inventory.observed_operations)} 已登记，"
                    "本轮没有新增绑定或状态，请勿重复提交该清单；"
                    "仍未找到目标绑定或已验证路线。"
                    "请执行当前可见的导航或恢复动作，或补充未登记的路线入口。"
                    if rediscovering else
                    "本轮清单没有新增引用、绑定或状态变化；不能再用 action=null "
                    "等待下一轮派发。请执行当前可见目标，或先恢复到目标区块。"
                )
                self.ledger.event(
                    "redundant_page_report_without_progress_rejected",
                    state_id=self.ledger.current_state_id,
                    task_id=task.task_id,
                )
                self._record_action_rejection(
                    self.ledger.tasks[task.task_id], issue)
                self.artifacts.checkpoint(self.ledger)
                continue

            if inventory_progress:
                self._clear_action_rejections()
            if turn.next_operation_ref:
                try:
                    previous_task = self.ledger.current_task()
                    task = self.scheduler.select_visible_operation(
                        self.ledger, turn.next_operation_ref, turn.strategy)
                    if task is previous_task:
                        turn = replace(turn, next_operation_ref="")
                    self._clear_action_rejections()
                except ValueError as exc:
                    self._record_action_rejection(self.ledger.current_task(), str(exc))
                    self.artifacts.checkpoint(self.ledger)
                    continue
            active_task = self.ledger.current_task()
            if (active_task is not None
                    and active_task.kind == "explore_operation"
                    and not turn.next_operation_ref
                    and turn.previous_action is None
                    and page_report is None
                    and turn.action is None
                    and not turn.current_task_result):
                issue = (
                    "本轮没有结算前一动作、登记新页面事实、执行 GUI 动作或"
                    "结算当前 Operation，因此没有产生任何探索进展。请立即执行"
                    "页面卡片中的目标 owner；若目标尚不可达，先用当前可见 owner"
                    "导航或用空 owner_ref 恢复，不能只等待下一轮。"
                )
                self.ledger.event(
                    "operation_turn_without_progress_rejected",
                    task_id=active_task.task_id,
                    operation_id=active_task.operation_id,
                )
                self._record_action_rejection(active_task, issue)
                self.artifacts.checkpoint(self.ledger)
                continue

            self.correction = ""
            if turn.current_task_result:
                active_task = self.ledger.current_task()
                if active_task is None or active_task.kind != "explore_operation":
                    self.correction = (
                        "current_task_result 只能结算当前 active 的操作任务"
                    )
                    self.artifacts.checkpoint(self.ledger)
                    continue
                self._clear_action_rejections()
                self.scheduler.settle(
                    self.ledger,
                    active_task,
                    result=turn.current_task_result,
                    reason=turn.reason,
                )
                self.ledger.event(
                    "current_task_settled",
                    task_id=active_task.task_id,
                    operation_id=active_task.operation_id,
                    result=turn.current_task_result,
                    reason=turn.reason,
                )
                self.artifacts.checkpoint(self.ledger)
                observation = self.env._get_obs() or observation
                continue
            if turn.action is not None:
                active_task = self.ledger.current_task()
                try:
                    bound_action = self._bind_action(active_task, turn.action)
                except ValueError as exc:
                    self._record_action_rejection(active_task, str(exc))
                    self.artifacts.checkpoint(self.ledger)
                    continue
                if (self.exploration_goal and active_task is None
                        and bound_action.operation_ref):
                    selected = self.ledger.operation_task(bound_action.operation_ref)
                    if selected is not None and selected.status in OPEN_TASK_STATES:
                        operation = self.ledger.operations[bound_action.operation_ref]
                        try:
                            active_task = self.scheduler.select_visible_operation(
                                self.ledger, operation.canonical_operation_id, turn.strategy)
                        except ValueError as exc:
                            self._record_action_rejection(None, str(exc))
                            self.artifacts.checkpoint(self.ledger)
                            continue
                if (active_task is None
                        and current_survey is not None
                        and current_survey.status in {"pending", "active"}
                        and bound_action.purpose in {"survey", "recover"}):
                    current_survey.status = "active"
                    self.ledger.current_task_id = current_survey.task_id
                    active_task = current_survey
                issue = self._validate_action(active_task, bound_action)
                if issue:
                    self._record_action_rejection(active_task, issue)
                    self.artifacts.checkpoint(self.ledger)
                    continue
                if self.actions_used >= self.max_actions:
                    stop_reason = "action_limit"
                    break
                self._clear_action_rejections()
                observation = self._execute(
                    task=active_task,
                    action=bound_action,
                    screenshot=screenshot,
                    agent_reason=turn.reason,
                )
                self.artifacts.checkpoint(self.ledger)
                continue

            self.artifacts.checkpoint(self.ledger)
            gaps = self.scheduler.gaps(self.ledger)
            if (self.exploration_goal and self.ledger.current_task() is None
                    and not self.pending_attempt_id and not self.resume_region_rediscovery_required
                    and turn.previous_action is None and not inventory_progress):
                stop_reason = "scope_idle"
                break
            if (not self.pending_attempt_id
                    and not self.resume_region_rediscovery_required
                    and not self.exploration_goal
                    and not any(task.status in OPEN_TASK_STATES
                                for task in self.ledger.tasks.values())):
                stop_reason = self._completion_reason(system_scope, screenshot)
                break
            observation = self.env._get_obs() or observation
        gaps = self.scheduler.gaps(self.ledger)
        if self.taskless_recovery_error:
            gaps.append(self.taskless_recovery_error)
        status = "complete" if stop_reason == "complete" and not gaps else "partial"
        self.artifacts.checkpoint(self.ledger)
        bundle_status = "compiled"
        bundle: Dict[str, Any] = {}
        bundle_error = ""
        try:
            bundle = compile_modular_bundle(
                self.ledger,
                output_root=self.output_root,
                app_name=self.app_name,
                stop_reason=stop_reason,
            )
        except (OSError, TypeError, ValueError) as exc:
            bundle_status = "compile_failed"
            bundle_error = str(exc)[:1000]
        completion = {
            "schema": "modular_completion.v3",
            "status": status,
            "stop_reason": stop_reason,
            **({"exploration_goal": self.exploration_goal} if self.exploration_goal else {}),
            "actions_used": self.actions_used,
            "model_turns": self.model_turns,
            "pages": len(self.ledger.pages),
            "states": len(self.ledger.states),
            "regions": len(self.ledger.regions),
            "region_variants": len(self.ledger.region_variants),
            "elements": len(self.ledger.elements),
            "operations": len(self.ledger.canonical_operations),
            "operation_bindings": len(self.ledger.operations),
            "tasks": logical_task_count(self.ledger),
            "task_bindings": len(self.ledger.tasks),
            "transitions": len(self.ledger.transitions),
            "gaps": gaps,
            "bundle_status": bundle_status,
            "bundle": bundle,
            "bundle_error": bundle_error,
        }
        self.artifacts.write_completion(completion)
        return ExplorationResult(
            status=status,
            stop_reason=stop_reason,
            actions_used=self.actions_used,
            model_turns=self.model_turns,
            output_root=self.output_root,
            gaps=tuple(gaps),
        )


def _build_explorer_agent(
    *,
    backend: str,
    transport_agent: Any,
    model: str,
    output_root: str,
    api_config: Optional[ExploreAPIConfig] = None,
) -> Any:
    backend_name = str(backend or "").strip().casefold()
    if backend_name == "qwen_api":
        return QwenExplorerAgent(
            transport=transport_agent,
            model=model,
            output_root=output_root,
        )
    if backend_name == "codex_cli":
        return CodexExplorerAgent(
            model=model,
            output_root=output_root,
        )
    if backend_name == "openai_api":
        if not isinstance(api_config, ExploreAPIConfig):
            raise ValueError("openai_api requires validated local API config")
        return OpenAIAPIExplorerAgent(
            base_url=api_config.base_url,
            api_key=api_config.api_key,
            model=api_config.model,
            reasoning_effort=api_config.reasoning_effort,
            timeout=api_config.timeout_seconds,
            output_root=output_root,
        )
    raise ValueError(f"unknown modular explore backend: {backend}")


def run(
    *,
    env: Any,
    app_name: str,
    output_root: str,
    initial_obs: Dict[str, Any],
    model: str,
    transport_agent: Any,
    max_actions: int,
    backend: str = "qwen_api",
    desktop_window_owner: Any = None,
    relaunch_fn: Any = None,
    resume_path: str = "",
    api_config: Optional[ExploreAPIConfig] = None,
    run_checkpoint: Any = None,
    package_versions: Optional[Mapping[str, str]] = None,
    seed_plan_digest: str = "",
    save_environment: Any = None,
    delete_environment: Any = None,
    defer_partition_review: bool = False,
) -> ExplorationResult:
    platform = str(getattr(env, "vm_platform", "desktop") or "desktop")
    agent = _build_explorer_agent(
        backend=backend,
        transport_agent=transport_agent,
        model=model,
        output_root=output_root,
        api_config=api_config,
    )
    runtime = ExplorationRuntime(
        env=env,
        app_name=app_name,
        platform=platform,
        output_root=output_root,
        agent=agent,
        max_actions=max_actions,
        desktop_window_owner=desktop_window_owner,
        relaunch_fn=relaunch_fn,
        run_checkpoint=run_checkpoint,
        package_versions=package_versions,
        seed_plan_digest=seed_plan_digest,
        save_environment=save_environment,
        delete_environment=delete_environment,
        defer_partition_review=defer_partition_review,
    )
    resume_observation = dict(initial_obs or {})
    if str(resume_path or "").strip():
        if runtime.scope.check() != "target":
            recovered = runtime.scope.recover()
            if isinstance(recovered, dict):
                resume_observation = dict(recovered)
        if runtime.scope.check() != "target":
            return ExplorationResult(
                status="partial",
                stop_reason="resume_scope_unresolved",
                actions_used=0,
                model_turns=0,
                output_root=output_root,
                gaps=(runtime.scope.last_reason or "resume scope unresolved",),
            )
        screenshot = resume_observation.get("screenshot")
        if (not isinstance(screenshot, (bytes, bytearray))
                or not screenshot
                or not runtime.restore(str(resume_path))):
            return ExplorationResult(
                status="partial",
                stop_reason="resume_location_unresolved",
                actions_used=0,
                model_turns=0,
                output_root=output_root,
                gaps=(runtime.resume_error or "resume location unresolved",),
            )
    result = runtime.run(resume_observation)
    if result.status == "complete" and run_checkpoint is not None \
            and delete_environment is not None:
        run_checkpoint.clear(delete_environment=delete_environment)
    return result


__all__ = ["ExplorationResult", "ExplorationRuntime", "run"]
