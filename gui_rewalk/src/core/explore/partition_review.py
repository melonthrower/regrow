"""Check a new visual inventory's partition before its IDs are committed."""
import hashlib
import json
from copy import deepcopy

from .contracts import ACTIVE_SURFACE_GUIDANCE, CONTROL_ACTION_GUIDANCE, ReportCorrections, HANDLING_GUIDANCE, ReportCorrectionExhausted
from .settlement import SettlementContractError
from dataclasses import asdict, replace

PROTOCOL = 'partition_qualification.v3'
SCHEMA = {'type': 'object', 'properties': {
    'protocol': {'type': 'string', 'enum': [PROTOCOL]},
    'decision': {'type': 'string', 'enum': ['same', 'different', 'uncertain']},
    'reason': {'type': 'string'},
    **{key: {'type': 'boolean'} for key in ('foreground_confirmed', 'partition_confirmed', 'controls_confirmed')},
    'blocking_issues': {'type': 'array', 'items': {'type': 'string'}},
    'operation_checks': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'path': {'type': 'string', 'description': '仅当前Element operations路径；Region操作不属于operation_checks隔离合同，真实错误用blocking_issues。'}, 'action': {'type': 'string'},
        'field': {'type': 'string', 'enum': ['handling']}, 'eligible': {'type': 'boolean'},
        'evidence': {'type': 'string'},
        'affected_paths': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['path', 'action', 'field', 'eligible', 'evidence', 'affected_paths'], 'additionalProperties': False}},
}, 'required': ['protocol', 'decision', 'reason', 'foreground_confirmed', 'partition_confirmed',
    'controls_confirmed', 'blocking_issues', 'operation_checks'], 'additionalProperties': False}

SCHEMA['properties']['omission_checks'] = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'region_path': {'type': 'string'}, 'image_sha256': {'type': 'string'},
    'box_1000': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
    'description': {'type': 'string'}, 'evidence': {'type': 'string'},
    'affected_paths': {'type': 'array', 'items': {'type': 'string'}},
    'independent_operations': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'path': {'type': 'string'}, 'evidence': {'type': 'string'},
        'dependencies': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['path', 'evidence', 'dependencies'], 'additionalProperties': False}},
    'exit_path': {'type': 'string'}, 'exit_evidence': {'type': 'string'},
}, 'required': ['region_path', 'image_sha256', 'box_1000', 'description', 'evidence',
    'affected_paths', 'independent_operations', 'exit_path', 'exit_evidence'], 'additionalProperties': False}}
SCHEMA['required'].append('omission_checks')

PROMPT = ACTIVE_SURFACE_GUIDANCE + "\n" + CONTROL_ACTION_GUIDANCE + "\n" + HANDLING_GUIDANCE + "\n" + """你是既有界面审核角色，检查主Agent新清单是否准确表达当前截图；不执行GUI、不判断历史身份。
scope.target_app和scope.platform由框架指定本次目标，不根据后方窗口标题另猜目标；目标名称本身不证明前景归属，仍须核对当前截图。
编号由框架管理：新region_ref/element_ref留空是正确的，不能要求补编号或编造引用。parent_ref整数为本报告0起始父行，字符串为已有Region引用；不要把父行序号当全局ID。
只检查影响分区/物理控件识别的明确错误，不争论同义名称或要求唯一分区数量：
1. 只清点当前接管输入的前景。被接管的后方窗口仅为图像上下文，不能登记Region/Element/Operation，即使标为defer也不允许。
2. 明确可见容器内部被拆成多个独立功能组时保留父容器和parent_ref；不虚构容器，不把父子合成同一身份。
3. 同一列表中仅数据不同、结构和基础操作同构的成员不按数据值各建Region类型；归列表Region，可选一个明确可见成员作代表。展开产生独立编辑任务上下文时须增结果Region；内联时属于可见来源容器的子区，触发控件保持来源职责。不同功能入口不能因外观同为列表项就省略。
4. 明确纯说明的静态标签/读数/对象标识归区块说明；不能编造操作。文字、数值或没有按钮边框本身不证明不可交互，可编辑内容和导航也可呈文字样式；交互语义不确定时保留为待探查候选，不把猜测当已证实错误。每个Element对应具体物理控件，不能把多个独立按钮概括成一个集合控件；代表法仅用于同质数据条目；独立配置选项、导航入口和同一对象内部的独立控件仍分别登记，不用一个代表替掉。
5. 当前图清晰可见的独立功能入口不能漏掉；截断内容可以保留未完成，不要求穷举滚动数据或进行GUI验证。
先检查完以上各项，一次列出所有能明确确认的相关错误，不只报告第一项。清单满足要求用same；有明确错误用different并在reason逐项用给出的path点名报告行/控件及最小修改；看不清用uncertain。不为补不确定功能编造按钮，不因界面未探索就拒绝正确可见清单。
若有repair_review，它只提供同一Attempt/截图的历史候选、意见和实际编辑事实，不是正确答案或新的动作授权。历史路径仅属于随附的原候选，不能直接当当前路径。对照当前图与page_report，在reason逐项说明此前问题已修、仍缺或证据不足；没有再提到不表示已修。继续检查当前全图和新增错误，特别核对replace/remove是否丢掉原本正确的独立控件。缺其他入口时应保留已正确对应的条目并新增缺项；一条确实混写多个按钮才需拆分；原条目错误才替换/移除，不能一概禁止replace。给主Agent的修改路径只使用当前page_report路径；登记不等于执行，不要求新增合同不支持的动作。
"""

PROMPT += """\n使用partition_qualification.v3。分别确认当前前景、分区、全部已报告控件对应；其余身份/来源/动作结果由原检查处理。
controls_confirmed只评价已报告控件是否准确，不代表清单完整；独立漏报由omission_checks表达。若已报告控件本身错误，写controls_confirmed=false及具体blocking_issues，并将omission_checks/operation_checks留空，交作者修正；不强迫确认不可信控件。
按scope及各操作reason核对handling。scope来自框架；reason只是主Agent的解释，不是授权事实。可见启用但当前范围禁止执行时，defer可合理，不因此拒绝清单或要求eligible=true。未明确的范围不能靠reason补造；语义或后果不清说明具体不确定点。
归属、遮挡、身份或落点依赖不确定放入blocking_issues，不能归为可隔离问题。
只有独立控件当前操作资格/handling争议可以operation_checks列出：精确到operations数组项的path、action、field=handling、eligible=false、当前可见依据evidence、完整影响范围affected_paths。影响其他操作/定位时必须阻断。
有独立争议仍输出different，不改为same。没有争议输出same；operation_checks可为空。
如qualification_gaps附带待复查操作，逐一根据当前图核对；只有新证据确实解除原资格争议才对其当前候选路径写eligible=true，并具体说明证据。不因重启、新截图或新路线假定资格恢复。
真正漏报的内容使用独立omission_checks，不冒充handling争议：仅当当前前景/分区/已报告控件均可信，缺项可定位且不影响任何已报告操作及退出路径时允许隔离。region_path必须指向可信当前报告Region，image_sha256复制当前观察摘要，box_1000为缺失可见内容在整屏归一化坐标中的局部框，不能用整张图代替定位；description/evidence具体说明遗漏及边界。affected_paths列所有受影响的已有操作；依赖漏项或未确认对象必须阻断；已报告可信控件之间的依赖完整列出并由程序核对引用，不为了放行清空。independent_operations逐一列出全部已报告Element和Region操作的path、可见独立性证据以及dependencies（使用当前报告路径）；不能用笼统“其余正确”代替依赖说明。exit_path引用当前已报告的可靠退出操作，exit_evidence说明为什么无需漏项就能安全退出。无法确认归属或可靠退出、遗漏参与当前动作结果、焦点或模态边界时使用blocking_issues。缺项不分配Operation ID或点击坐标，不在此直接补清单；有遗漏仍different。没有遗漏用空数组，原清单和different保留。
"""


def operation_paths(report):
    paths = {f'/regions/{region_index}/elements/{element_index}/operations/{operation_index}': operation
        for region_index, region in enumerate(report.regions)
        for element_index, element in enumerate(region.elements)
        for operation_index, operation in enumerate(element.operations)}
    paths.update({f'/regions/{region_index}/region_operations/{operation_index}': operation
        for region_index, region in enumerate(report.regions)
        for operation_index, operation in enumerate(region.region_operations)})
    return paths


def valid_omissions(report, review, image_sha256):
    omissions = review.get('omission_checks')
    if not isinstance(omissions, list):
        return False
    paths = operation_paths(report)
    disputed_paths = {item.get('path') for item in review.get('operation_checks', [])
        if isinstance(item, dict) and item.get('eligible') is False}
    for item in omissions:
        if not isinstance(item, dict):
            return False
        box = item.get('box_1000')
        independent = item.get('independent_operations')
        if (item.get('region_path') not in {f'/regions/{index}' for index in range(len(report.regions))}
                or item.get('image_sha256') != image_sha256 or not paths
                or not isinstance(box, list) or len(box) != 4
                or any(type(value) not in (int, float) or not 0 <= value <= 1000 for value in box)
                or not (box[0] < box[2] and box[1] < box[3])
                or box == [0, 0, 1000, 1000]
                or any(not str(item.get(key) or '').strip() for key in ('description', 'evidence', 'exit_evidence'))
                or item.get('affected_paths') != [] or item.get('exit_path') not in paths
                or item.get('exit_path') in disputed_paths
                or paths[item['exit_path']].handling == 'defer'
                or paths[item['exit_path']].action not in {'click', 'back'}
                or not isinstance(independent, list) or len(independent) != len(paths)):
            return False
        seen = set()
        for check in independent:
            if (not isinstance(check, dict) or check.get('path') not in paths
                    or check['path'] in seen or not isinstance(check.get('dependencies'), list)
                    or any(not isinstance(dependency, str) or dependency not in paths
                        or dependency == check['path'] or dependency in disputed_paths
                        for dependency in check.get('dependencies', []))
                    or not str(check.get('evidence') or '').strip()):
                return False
            seen.add(check['path'])
        if seen != paths.keys():
            return False
    return True


def qualification_gaps(ledger):
    gaps = {}
    for event in ledger.events:
        payload = event['payload']
        if event['kind'] == 'operation_qualification_isolated':
            gaps[payload['operation_id']] = payload
        elif event['kind'] == 'operation_qualification_resolved':
            gaps.pop(payload['operation_id'], None)
    return {ref: gap for ref, gap in gaps.items() if ref in ledger.operations}


def route_links(ledger):
    return sorted({(edge.source_state_id, edge.target_state_id, str(edge.action.get('operation_ref', '')))
        for edge in ledger.transitions if ledger.attempts.get(edge.attempt_id)
        and ledger.attempts[edge.attempt_id].outcome == 'success'})


def active_revisits(ledger):
    active = set()
    for event in ledger.events:
        if event['kind'] == 'qualification_revisit_requested':
            active.add(event['payload']['operation_id'])
        elif event['kind'] in {'qualification_revisit_finished', 'operation_qualification_resolved'}:
            active.discard(event['payload']['operation_id'])
    return active & qualification_gaps(ledger).keys()


def wake_qualification_revisits(ledger):
    from .region_routes import plan_region_route
    for operation_id, gap in qualification_gaps(ledger).items():
        operation = ledger.operations[operation_id]
        task = ledger.operation_task(operation_id)
        if task is None or operation.attempt_count or task.status != 'deferred':
            continue
        seen = gap.get('route_links', [])
        for event in ledger.events:
            if event['kind'] == 'qualification_revisit_requested' and event['payload']['operation_id'] == operation_id:
                seen = event['payload']['route_links']
        route = plan_region_route(ledger, current_state_id=ledger.current_state_id, target_region_id=operation.region_id)
        known = {tuple(link) for link in seen}
        edges = {edge.transition_id: edge for edge in ledger.transitions}
        new_route = any((edges[step['evidence_transition_ref']].source_state_id,
            step['expected_target_state_ref'], step['operation_ref']) not in known for step in route['steps'])
        if route['status'] != 'ready' or not new_route:
            continue
        task.status = 'pending'
        ledger.event('qualification_revisit_requested', operation_id=operation_id, route=route,
            route_links=route_links(ledger), reason='New verified route permits observation, not execution')


def qualification_report(report, review):
    checks = {item['path']: item for item in (review or {}).get('operation_checks', [])}
    return replace(report, survey_complete=False if (review or {}).get('omission_checks') else report.survey_complete,
        regions=[replace(region, elements=[replace(element, operations=[
        replace(operation, handling='defer', reason=checks[path]['evidence'])
        if path in checks and not checks[path]['eligible'] else operation
        for operation_index, operation in enumerate(element.operations)
        for path in [f'/regions/{region_index}/elements/{element_index}/operations/{operation_index}']])
        for element_index, element in enumerate(region.elements)])
        for region_index, region in enumerate(report.regions)])


def validate_qualification_dependencies(report, review, ledger, previous_action, current_screen=None):
    omissions = (review or {}).get('omission_checks') or []
    if omissions and previous_action:
        operation_paths_by_element = {}
        operation_paths_by_region = {}
        for path, operation in operation_paths(report).items():
            parts = path.split('/')
            if 'elements' in parts:
                operation_paths_by_element.setdefault(
                    report.regions[int(parts[2])].elements[int(parts[4])].element_ref, set()).add(path)
            else:
                operation_paths_by_region.setdefault(
                    report.regions[int(parts[2])].region_ref, set()).add(path)
        completed_paths = set()
        completed_regions = set()
        for item in previous_action.element_actions or ():
            if item.completed:
                paths = operation_paths_by_element.get(item.element_ref, set())
                completed_paths.update(paths)
                completed_regions.update(report.regions[int(path.split('/')[2])].region_ref for path in paths)
        for item in previous_action.region_actions or ():
            if item.completed:
                completed_paths.update(operation_paths_by_region.get(item.region_ref, ()))
                completed_regions.add(item.region_ref)
        attempt = ledger.attempts.get(previous_action.attempt_ref)
        source_operation = (ledger.operations.get(attempt.action.get('operation_ref', ''))
                            if attempt is not None else None)
        source_state = ledger.states.get(attempt.source_state_id) if attempt is not None else None
        completed_source_action = bool(
            previous_action.attempt_ref == attempt.attempt_id
            and (completed_paths or any(
                item.completed for item in previous_action.element_actions or ()
            ) or any(item.completed for item in previous_action.region_actions or ()))
        ) if attempt is not None else False
        landing_has_new_state_evidence = bool(
            current_screen is not None
            and current_screen.identity == 'new_state'
            and not current_screen.state_ref
            and current_screen.page_ref
            and source_state is not None
            and current_screen.page_ref == source_state.page_id
            and current_screen.state_name.strip()
            and current_screen.state_summary.strip()
            and any(effect.get('change') in {'disappeared', 'appeared', 'updated'}
                    and effect.get('cause') == 'action'
                    for effect in previous_action.region_effects or ())
        )
        cross_page_landing = bool(
            current_screen is not None
            and current_screen.identity in {'known', 'new_state'}
            and attempt is not None
            and attempt.source_state_id
            and source_operation is not None
            and completed_source_action
            and previous_action.attempt_ref == attempt.attempt_id
            and (
                (bool(current_screen.state_ref)
                 and current_screen.state_ref != attempt.source_state_id)
                or landing_has_new_state_evidence
            )
        )
        # Ownerless Back settles navigation, not a fabricated completed control.
        # This branch only admits a known landing with explicit disappearance
        # evidence; the normal visual identity and final effect checks still run.
        navigation_regions = set()
        if (attempt is not None and source_state is not None
                and attempt.purpose in {'route', 'recover'}
                and attempt.action.get('kind') == 'back'
                and not attempt.action.get('operation_ref')
                and not attempt.action.get('owner_ref')
                and attempt.before_ref and attempt.after_ref
                and current_screen is not None and current_screen.identity == 'known'
                and current_screen.state_ref in ledger.states
                and ledger.states[current_screen.state_ref].page_id == current_screen.page_ref
                and all((review or {}).get(key) is True for key in (
                    'foreground_confirmed', 'partition_confirmed', 'controls_confirmed'))):
            source_regions = {item.region_id for item in ledger.state_occurrences(attempt.source_state_id)}
            target_regions = {item.region_id for item in ledger.state_occurrences(current_screen.state_ref)}
            reported_regions = {item.region_ref for item in report.regions}
            effects = previous_action.region_effects or ()
            if effects and all(effect.get('cause') == 'action'
                    and effect.get('change') == 'disappeared'
                    and effect.get('report_index') is None
                    and effect.get('region_ref') in source_regions - target_regions - reported_regions
                    for effect in effects):
                navigation_regions = {effect['region_ref'] for effect in effects}
        if not completed_paths and not cross_page_landing and not navigation_regions:
            raise SettlementContractError(code='PARTITION_RESULT_DEPENDENCY', field_path='page_report',
                expected='a pending action must map to a reported completed operation before omission admission',
                received=previous_action.attempt_ref,
                message='无法把待结算动作绑定到当前清单的已报告操作；漏项可能影响动作结果，不能隔离。')
        for omission in omissions:
            region_index = str(omission.get('region_path', '')).rsplit('/', 1)[-1]
            try:
                omission_region = report.regions[int(region_index)].region_ref
            except (ValueError, IndexError):
                omission_region = ''
            if navigation_regions and omission_region in navigation_regions:
                raise SettlementContractError(code='PARTITION_RESULT_DEPENDENCY', field_path='page_report',
                    expected='omission independent of the confirmed navigation result',
                    received=previous_action.attempt_ref,
                    message='遗漏影响导航结果的Region，不能隔离。')
            omission_paths = operation_paths_by_region.get(omission_region, set())
            dependencies = {dependency
                for item in omission.get('independent_operations', [])
                for dependency in item.get('dependencies', [])}
            source_paths = {path for path, operation in operation_paths(report).items()
                            if operation.operation_ref in {
                                source_operation.operation_id,
                                source_operation.canonical_operation_id,
                            }} if source_operation is not None else set()
            if (not cross_page_landing and
                    (omission_region in completed_regions or completed_paths & (omission_paths | dependencies))):
                raise SettlementContractError(code='PARTITION_RESULT_DEPENDENCY', field_path='page_report',
                    expected='omission must not contain or depend on the pending action operation',
                    received=previous_action.attempt_ref,
                    message='独立遗漏与待结算动作存在当前清单依赖，不能局部放行。')
            if cross_page_landing and (omission_region == source_operation.region_id
                                      or source_paths & (omission_paths | dependencies)):
                raise SettlementContractError(code='PARTITION_RESULT_DEPENDENCY', field_path='page_report',
                    expected='cross-page omission must not affect the source operation or its current landing evidence',
                    received=previous_action.attempt_ref,
                    message='跨页落地虽不要求来源控件出现在后帧，但遗漏仍指向来源操作或其依赖，不能隔离。')
    for item in (review or {}).get('operation_checks', []):
        if item['eligible']:
            continue
        parts = item['path'].split('/')
        element = report.regions[int(parts[2])].elements[int(parts[4])]
        operation = element.operations[int(parts[6])]
        completed = previous_action and any(action.completed and action.element_ref == element.element_ref
            for action in previous_action.element_actions)
        attempt = ledger.attempts.get(previous_action.attempt_ref) if previous_action else None
        bound = ledger.operations.get(attempt.action.get('operation_ref', '')) if attempt else None
        if (completed or attempt and bound is None or bound and (
                bound.element_id == element.element_ref or operation.operation_ref in
                {bound.operation_id, bound.canonical_operation_id})):
            raise SettlementContractError(code='PARTITION_RESULT_DEPENDENCY', field_path=item['path'],
                expected='qualification dispute independent of the pending result', received=item['evidence'],
                message='争议操作参与当前动作结果，不能局部放行。')


def verify_partition(agent, *, report, screenshot, cache, force=False, attempt_ref='', edit_trace=None, gaps=None, inventory_gaps=None, run_scope=None, corrections=None):
    cache.pop('qualification', None)
    scope = (attempt_ref, hashlib.sha256(screenshot).hexdigest(), PROTOCOL,
             json.dumps(run_scope or {}, ensure_ascii=False, sort_keys=True))
    if cache.get('scope') != scope:
        cache.clear()
        cache['scope'] = scope
    if report is None or (not force and not any(
            not r.region_ref or any(not e.element_ref for e in r.elements)
            for r in report.regions)):
        return None
    reviewer = getattr(agent, 'review_partition', None)
    if not callable(reviewer):
        return None
    proposal = {'regions': [
        {'report_index': i, 'path': f'/regions/{i}', 'region_ref': r.region_ref, 'parent_ref': r.parent_ref,
         'name': r.name, 'summary': r.summary,
         'elements': [{'path': f'/regions/{i}/elements/{j}', 'element_ref': e.element_ref, 'name': e.name,
                       'observation': e.observation,
                       'operations': [{'action': op.action, 'target': op.target, 'handling': op.handling, 'reason': op.reason}
                                      for op in e.operations]} for j, e in enumerate(r.elements)],
         'region_operations': [{'path': f'/regions/{i}/region_operations/{index}',
                                'action': op.action, 'direction': op.direction,
                                'target': op.target, 'handling': op.handling, 'reason': op.reason}
                               for index, op in enumerate(r.region_operations)]}
        for i, r in enumerate(report.regions)]}
    key = (json.dumps(proposal, ensure_ascii=False, sort_keys=True),
           json.dumps(edit_trace or [], ensure_ascii=False, sort_keys=True),
           PROTOCOL, json.dumps(run_scope or {}, ensure_ascii=False, sort_keys=True),
           json.dumps(gaps or {}, ensure_ascii=False, sort_keys=True),
           json.dumps(inventory_gaps or {}, ensure_ascii=False, sort_keys=True))
    if cache.get('key') == key or (cache.get('reviewer_error')
            and cache.get('key', (None,))[0] == key[0]):
        result = cache['result']
    else:
        payload = {'page_report': proposal, 'image_sha256': scope[1], 'scope': run_scope or {}, 'protocol': PROTOCOL}
        if cache.get('reviewer_error'):
            payload['reviewer_correction'] = cache['reviewer_error']
        payload['qualification_gaps'] = gaps or {}
        payload['inventory_gaps'] = inventory_gaps or {}
        previous = cache.get('reviews', [])
        if previous or edit_trace:
            payload['repair_review'] = {'attempt_ref': attempt_ref, 'image_sha256': scope[1],
                'previous_reviews': deepcopy(previous), 'edits': deepcopy(edit_trace or [])}
        try:
            result = reviewer(payload=payload, screenshots=[screenshot])
        except (TypeError, ValueError) as error:
            result = {'decision': 'invalid', 'reason': str(error), 'protocol': PROTOCOL}
        # Only actual reviews enter the same-observation history; a cached
        # rejection neither adds a round nor drops an earlier unmentioned issue.
        cache['reviews'] = [*previous, {'candidate': deepcopy(proposal),
            'decision': result.get('decision') if isinstance(result, dict) else None,
            'reason': str(result.get('reason') or '') if isinstance(result, dict) else ''}][-ReportCorrections().limit:]
        cache.update(key=key, result=result)
    decision = result.get('decision') if isinstance(result, dict) else None
    reason = str(result.get('reason') or '').strip() if isinstance(result, dict) else ''
    qualification = None
    if isinstance(result, dict) and result.get('protocol') == PROTOCOL:
        paths = operation_paths(report)
        checks = result.get('operation_checks')
        valid = (all(result.get(key) is True for key in (
            'foreground_confirmed', 'partition_confirmed', 'controls_confirmed'))
            and result.get('blocking_issues') == [] and isinstance(checks, list)
            and valid_omissions(report, result, scope[1]))
        seen = set()
        for item in checks if isinstance(checks, list) else []:
            path = item.get('path') if isinstance(item, dict) else None
            if (not isinstance(path, str) or path not in paths or '/elements/' not in path or path in seen or item.get('action') != paths[path].action
                    or item.get('field') != 'handling' or type(item.get('eligible')) is not bool
                    or not str(item.get('evidence') or '').strip() or item.get('affected_paths') != [path]):
                valid = False
            if isinstance(path, str):
                seen.add(path)
        disputed = any(item.get('eligible') is False for item in (checks if isinstance(checks, list) else []) if isinstance(item, dict))
        disputed = disputed or bool(result.get('omission_checks'))
        if valid and reason and ((decision == 'different' and disputed) or (decision == 'same' and not disputed)):
            qualification = {**deepcopy(result), 'candidate': asdict(report), 'image_sha256': scope[1]}
            cache['qualification'] = qualification
        elif not (decision in {'different', 'uncertain'} and reason
                  and isinstance(result.get('blocking_issues'), list) and result['blocking_issues']
                  and not result.get('omission_checks') and not checks):
            decision = 'invalid qualification evidence'
    elif isinstance(result, dict) and result.get('protocol'):
        decision = 'unsupported qualification protocol'
    if (decision not in {'same', 'different', 'uncertain'} or not reason) and corrections is not None:
        detail = 'Reviewer输出未通过本轮合同；只修正Reviewer输出，不要求主Agent迎合非法审核。'
        field_path = 'reviewer_output'
        if isinstance(result, dict):
            if result.get('protocol') != PROTOCOL:
                field_path = 'protocol'
                detail = f"protocol收到{result.get('protocol')!r}，期望{PROTOCOL!r}；本轮审核未准入，主Agent候选未修改。"
            missing = [key for key in SCHEMA['required'] if key not in result]
            if missing:
                field_path = missing[0]
                detail = f"Reviewer缺少必填字段 {', '.join(missing)}；补齐这些字段后重新审核，不能把缺字段解释为主Agent清单遗漏。"
            for index, check in enumerate(result.get('operation_checks') if isinstance(result.get('operation_checks'), list) else []):
                if isinstance(check, dict) and type(check.get('eligible')) is not bool:
                    field_path = f'operation_checks[{index}].eligible'
                    detail = f'收到{check.get("eligible")!r}，期望boolean；eligible是当前前提与scope内的执行资格。'
                elif isinstance(check, dict):
                    path = check.get('path')
                    if not isinstance(path, str) or path not in paths or '/elements/' not in path:
                        field_path = f'operation_checks[{index}].path'
                        detail = (f"收到路径{path!r}；operation_checks仅接受本候选Element的operations路径，不接受Region操作或历史路径。"
                            "普通纵向scroll按既有合同登记record，未见内容通过survey_complete=false继续清点，不因可安全滚动就要求explore。"
                            "若确有不可隔离的结构/Region操作错误，在blocking_issues列具体问题并清空隔离检查；不要求主Agent迁就非法路径。")
                    missing = [key for key in SCHEMA['properties']['operation_checks']['items']['required'] if key not in check]
                    if missing:
                        field_path = f'operation_checks[{index}]'
                        detail = f"Reviewer的operation_checks[{index}]缺少 {', '.join(missing)}；补齐审核证明，不要求主Agent修改清单。"
            omissions = result.get('omission_checks')
            for index, omission in enumerate(omissions if isinstance(omissions, list) else []):
                if isinstance(omission, dict):
                    missing = [key for key in SCHEMA['properties']['omission_checks']['items']['required'] if key not in omission]
                    if missing:
                        field_path = f'omission_checks[{index}]'
                        detail = f"Reviewer的omission_checks[{index}]缺少 {', '.join(missing)}；补齐局部独立性证明，不要求主Agent修改清单。"
                if isinstance(omission, dict) and omission.get('box_1000') == [0, 0, 1000, 1000]:
                    field_path = f'omission_checks[{index}].box_1000'
                    detail = f'omission_checks[{index}].box_1000收到整屏框；需要真实局部边界及独立性证据，不得编造。'
            if result.get('decision') not in {'same', 'different', 'uncertain'}:
                detail += ' decision必须是same、different或uncertain。'
            if (any(result.get(key) is False for key in (
                    'foreground_confirmed', 'partition_confirmed', 'controls_confirmed'))
                    and result.get('blocking_issues') == []):
                field_path = 'blocking_issues'
                detail = ('确认字段为false但blocking_issues为空；请在blocking_issues写具体路径、依据或不确定点，'
                    'controls_confirmed指已报告控件准确性，不是全清单完整性；如已报告控件错误，保留false并将omission_checks/operation_checks置空，具体错误写blocking_issues。'
                    '普通different/uncertain拒绝不需要局部准入证明。候选尚未改变，作者还未收到合法修改意见。')
        error = SettlementContractError(code='PARTITION_REVIEWER_CONTRACT', field_path=field_path,
            expected=PROTOCOL, received=str(result)[:600], message=detail)
        if cache.get('reviewer_error'):
            raise SettlementContractError(code='PARTITION_VISUAL_UNCONFIRMED', field_path='page_report',
                expected='作者据当前截图核对候选；修后仍需原审核', received=str(decision),
                message=f'Reviewer修复一次后仍未满足合同：{detail}。'
                    f'未经确认的语义线索（不是准入判决）：{reason}。'
                    '候选尚未发布；按本轮提交合同修正，不迎合未经验证的功能猜测。')
        cache['reviewer_error'] = {'responsible_role': 'partition_reviewer', 'error': str(error),
            'application_state': '审核未准入，主Agent候选未修改', 'next_step': '只修正本Reviewer输出；缺证据则保留阻断'}
        cache.pop('key', None)
        if corrections.reject(error, 'partition_reviewer'):
            return verify_partition(agent, report=report, screenshot=screenshot, cache=cache, force=force,
                attempt_ref=attempt_ref, edit_trace=edit_trace, gaps=gaps, inventory_gaps=inventory_gaps,
                run_scope=run_scope, corrections=corrections)
        exhausted = ReportCorrectionExhausted(str(error))
        exhausted.recipient = 'partition_reviewer'
        raise exhausted
    cache.pop('reviewer_error', None)
    if (decision != 'same' and qualification is None) or not reason:
        if isinstance(result, dict):
            for index, omission in enumerate(result.get('omission_checks') if isinstance(result.get('omission_checks'), list) else []):
                if isinstance(omission, dict) and omission.get('box_1000') == [0, 0, 1000, 1000]:
                    reason += (f'；omission_checks[{index}].box_1000 是整屏框，未提供漏项局部边界，'
                        '不能证明独立遗漏准入。主Agent应按当前截图补全清单；'
                        '该Reviewer框不是可执行坐标或已批准的局部证据。')
        raise SettlementContractError(code='PARTITION_VISUAL_UNCONFIRMED',
            field_path='page_report', expected='visible functional containers and concrete controls',
            received=str(decision),
            message=f'新清单分区未通过视觉核对：{reason or "审核回复无有效判定"}。'
                    '只修正指出的边界/控件与必要父引用，保留无关正确内容，不执行GUI或编造动作。')
    return reason
