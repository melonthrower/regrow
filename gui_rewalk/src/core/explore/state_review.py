"""Visual check before reusing an already inventoried State on a changed frame."""
from __future__ import annotations

import hashlib

from .contracts import ACTIVE_SURFACE_GUIDANCE
from .settlement import SettlementContractError

PROMPT = ACTIVE_SURFACE_GUIDANCE + "\n" + """你是既有界面身份审核角色，本次核对主Agent拟复用的已知State。
本次唯一图片是最新完整截图；文字是候选State的历史清单，不证明当前可见。先独立读图，再逐区对照历史控件。
比较当前可交互前景、功能对象和Region/控件组织，不能仅因同一应用、导航或Region名称就判same。
同一功能中的时间、输入值、选中态、同质数据成员变化、滚动视口变化本身仍可same；不要因像素变化创建State。
若出现独立编辑/详情上下文、模态层或操作集合实质变化，而旧清单不能表达当前功能组织，则different；特别检查原列表成员展开后的新功能，不能只更新旧区块说明而遗漏控件。
同一State仍可增量补漏，不将原清单漏项自动当新State。证据不足用uncertain。
先只看当前图，逐个历史Region填写region_checks：present/absent/uncertain，以及当前图实际可见、可直接交互的控件名称current_controls。未出现的子菜单不能因父入口仍可见就写present，历史清单不能代替当前图证据。
然后判断same/different/uncertain；same必须有完整、无冲突的逐区可见证据，功能组成变化用different，不能确定用uncertain。不改编号、不生成动作或因果。different后主Agent可复用真正匹配的其他已知State，或登记新State，不强制新建。
"""
SCHEMA = {'type': 'object', 'properties': {
    'decision': {'type': 'string', 'enum': ['same', 'different', 'uncertain']},
    'reason': {'type': 'string', 'minLength': 1},
    'region_checks': {'type':'array', 'items': {'type':'object', 'properties': {
        'region_ref': {'type':'string'},
        'presence': {'type':'string','enum':['present','absent','uncertain']},
        'current_controls': {'type':'array','items':{'type':'string'}},
    }, 'required':['region_ref','presence','current_controls'], 'additionalProperties':False}},
}, 'required': ['decision', 'reason', 'region_checks'], 'additionalProperties': False}


def verify_known_state(ledger, agent, artifacts, *, screen, screenshot, frame_ref,
                       approved_key=()):
    state = ledger.states.get(screen.state_ref)
    if (state is None or state.page_id != screen.page_ref
            or not state.survey_complete or screen.identity == 'uncertain'):
        return ()
    reviewer = getattr(agent, 'review_known_state', None)
    if not callable(reviewer):
        # Non-model clients use the existing structural protocol. No visual
        # approval is returned or recorded for them.
        return ()
    try:
        known = artifacts.read(state.screenshot_ref)
    except OSError as exc:
        raise SettlementContractError(code='STATE_VISUAL_UNCONFIRMED', field_path='screen',
            expected='readable known-State representative image, or new_state',
            received=state.screenshot_ref,
            message='旧State代表图不可读，不能确认整体复用；可用new_state清点当前前景，不猜旧身份') from exc
    regions = [{'region_ref': o.region_id, 'name': o.name, 'summary': o.summary,
                'parent_occurrence_ref': o.parent_occurrence_id,
                'controls': [{'element_ref': e.element_id, 'name': e.name}
                             for e in ledger.variant_elements(o.variant_id)]}
               for o in ledger.state_occurrences(state.state_id)]
    key = (state.state_id, hashlib.sha256(known).hexdigest(),
           hashlib.sha256(screenshot).hexdigest(), repr(regions))
    if key == approved_key:
        return key
    result = reviewer(payload={'state_ref': state.state_id, 'page_ref': state.page_id,
        'historical_summary': state.summary, 'historical_regions': regions,
        'known_screenshot_ref': state.screenshot_ref, 'current_screenshot_ref': frame_ref},
        screenshots=[screenshot])
    decision = result.get('decision') if isinstance(result, dict) else None
    reason = str(result.get('reason') or '').strip() if isinstance(result, dict) else ''
    checks = result.get('region_checks') if isinstance(result, dict) else None
    expected = {r['region_ref']: r for r in regions}
    valid_checks = (isinstance(checks, list)
        and all(isinstance(c, dict) for c in checks)
        and len(checks) == len(expected)
        and {c.get('region_ref') for c in checks} == set(expected))
    if decision == 'same' and (not valid_checks or any(
            c.get('presence') != 'present'
            or not isinstance(c.get('current_controls'), list)
            or (expected[c['region_ref']]['controls'] and not any(
                isinstance(name, str) and name.strip() for name in c['current_controls']))
            for c in (checks if valid_checks else []))):
        decision = 'uncertain'
        reason += f'；逐区当前控件证据缺失或与same冲突：{checks!r}'
    if decision != 'same' or not reason:
        raise SettlementContractError(code='STATE_VISUAL_UNCONFIRMED', field_path='screen',
            expected='visually supported State with current Region/control evidence',
            received=str(decision),
            message=f'旧State {state.state_id}视觉复用未确认：{reason or "审核回复无有效判定"}。'
                    '请据最新图修正screen和清单；可复用真正匹配的其他已知State，实质新功能用new_state并留空state_ref，'
                    '不同目的地用new_page。可保留真正共享的Region候选，不用旧引用组合掩盖新控件。')
    ledger.event('known_state_visually_confirmed', state_ref=state.state_id,
                 known_screenshot_ref=state.screenshot_ref,
                 current_screenshot_ref=frame_ref, reason=reason, region_checks=checks)
    return key
