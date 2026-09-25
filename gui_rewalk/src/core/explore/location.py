"""Current application Page and material State binding."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import PageReport, ScreenReport
from .ledger import ExplorationLedger
from .models import Page, PageState, Task
from .settlement import SettlementContractError


@dataclass(frozen=True)
class LocationResult:
    ok: bool
    ledger: ExplorationLedger
    page_id: str = ""
    state_id: str = ""
    issue: str = ""
    created_state: bool = False


def _name_key(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def validate_state_composition(
    ledger: ExplorationLedger, screen: ScreenReport, report: PageReport | None,
) -> None:
    """A partial Region observation does not establish a complete State identity."""
    state = ledger.states.get(screen.state_ref)
    if (state is None or not state.survey_complete
            or state.page_id != screen.page_ref or screen.identity == "uncertain"):
        return
    expected = {item.region_id for item in ledger.state_occurrences(state.state_id)}
    reported = {item.region_ref for item in report.regions} if report else set()
    if expected and reported == expected:
        return
    raise SettlementContractError(
        code="STATE_COMPOSITION_UNCONFIRMED", field_path="screen",
        expected=f"fresh确认完整Region组合 {sorted(expected)}，或用new_state记录局部观察",
        received=f"State {state.state_id}，本轮Region refs {sorted(reported)}",
        message=((f"当前位置已确认为{ledger.current_state_id}；若无新结构请保持该State，"
                  "任务的历史来源编号不是当前位置。" if ledger.current_state_id else "") +
                 "局部Region或仅改编号不能证明整个已完成State相同。若最新图确为该State，"
                 "在page_report列出其全部可见Region引用，已知控件/操作列表可空；"
                 "组合不同或只确认局部时用new_state并将state_ref留空，不改变旧State，"
                 "不要为凑旧State而复制实际不可见的Region。"),
    )


def bind_screen(
    ledger: ExplorationLedger,
    screen: ScreenReport,
    *,
    screenshot_ref: str,
) -> LocationResult:
    """Bind a model observation without deriving identity from its wording."""
    staged = ledger.clone()
    if screen.identity == "uncertain":
        return LocationResult(
            False, ledger, issue=(
                "当前页面身份仍不确定；请根据截图与已知页面记录明确复用或新建，"
                "不要在身份未定时登记区块或执行功能动作。"
            ),
        )

    created_state = False
    exact_page = staged.pages.get(screen.page_ref)
    exact_state = staged.states.get(screen.state_ref)
    exact_known = (
        exact_page is not None
        and exact_state is not None
        and exact_state.page_id == exact_page.page_id
    )
    if screen.identity == "known" or exact_known:
        page = staged.pages.get(screen.page_ref)
        state = staged.states.get(screen.state_ref)
        if page is None:
            return LocationResult(False, ledger, issue=(
                f"未知页面编号 {screen.page_ref}；请使用状态栏中存在的编号。"))
        if state is None:
            return LocationResult(False, ledger, issue=(
                f"未知状态编号 {screen.state_ref}；请使用状态栏中存在的编号。"))
        if state.page_id != page.page_id:
            owner = staged.pages.get(state.page_id)
            owner_text = (
                f"{state.page_id}（{owner.name}）" if owner else state.page_id
            )
            return LocationResult(False, ledger, issue=(
                f"状态 {screen.state_ref} 属于页面 {owner_text}，不是 "
                f"{screen.page_ref}；若当前截图是该状态，请改用正确的 "
                "page_ref。"))
        page_id, state_id = page.page_id, state.state_id
    else:
        if screen.identity == "new_state":
            page = staged.pages.get(screen.page_ref)
            if page is None:
                return LocationResult(False, ledger, issue=(
                    f"screen.page_ref={screen.page_ref}：要新增状态的页面编号不存在；"
                    "同一页面的新状态请复制已知 page_ref，真正的新页面用 identity=new_page，不要编造 Page 编号。"))
            page_id = page.page_id
        else:
            same_name = [
                page for page in staged.pages.values()
                if _name_key(page.name) == _name_key(screen.page_name)
            ]
            if same_name:
                existing = "、".join(
                    f"{page.page_id}（{page.name}）" for page in same_name)
                return LocationResult(False, ledger, issue=(
                    f"拟新增页面名称“{screen.page_name}”与已登记页面 "
                    f"{existing} 精确同名。框架不会仅凭名称自动合并，也不会"
                    "再建立同名 Page；若当前截图属于其中一个页面，请改用 "
                    "identity=known 及其精确 page_ref/state_ref；若确实是不同"
                    "主要功能页面，请给出能稳定区分功能目的地的页面名称。"
                ))
            page_id = staged.mint("page")
            staged.pages[page_id] = Page(
                page_id=page_id,
                name=screen.page_name,
                summary=screen.page_summary,
            )
        state_id = staged.mint("state")
        staged.states[state_id] = PageState(
            state_id=state_id,
            page_id=page_id,
            name=screen.state_name,
            summary=screen.state_summary,
            screenshot_ref=screenshot_ref,
        )
        staged.pages[page_id].state_ids.append(state_id)
        task_id = staged.mint("task")
        staged.tasks[task_id] = Task(
            task_id=task_id,
            kind="survey_page",
            status="pending",
            state_id=state_id,
            created_seq=len(staged.tasks) + 1,
        )
        staged.event(
            "state_registered",
            page_id=page_id,
            state_id=state_id,
            screenshot_ref=screenshot_ref,
        )
        created_state = True

    staged.current_page_id = page_id
    staged.current_state_id = state_id
    return LocationResult(
        True,
        staged,
        page_id=page_id,
        state_id=state_id,
        created_state=created_state,
    )


__all__ = ["LocationResult", "bind_screen", "validate_state_composition"]
