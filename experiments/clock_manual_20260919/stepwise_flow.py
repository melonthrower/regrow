"""Assemble stepwise requests and sequence execution for live runs and replay.

Evidence records: region_evidence. Target association: action_binding.
The live coordinator is run_task_step and uses StepwiseFlow.execute;
choose_from_graph is the saved-graph replay adapter.
"""
from copy import deepcopy
import time


class StepwiseFlow:
    def __init__(self, model, deliver, record):
        self.model, self.deliver, self.record = model, deliver, record
        self.phase = 'observe'
        self.proposal = None
        self.receipt = None
        self.binding = None

    def _require(self, phase):
        if self.phase != phase:
            raise ValueError(f'expected {phase}, current phase is {self.phase}')

    def observe(self, request):
        self._require('observe')
        result = self.model('observe', request)
        self.record('observe', deepcopy(result))
        self.phase = 'choose'
        return result

    def choose(self, request):
        self._require('choose')
        result = self.model('choose', request)
        self.record('choose', deepcopy(result))
        self.proposal = deepcopy(result)
        self.phase = 'execute' if result.get('action') != 'none' else 'paused'
        return result

    def choose_from_graph(self, root, graph, observation_ref, region_ref):
        self._require('choose')
        request = assemble_region_choice(root, graph, observation_ref, region_ref)
        self.record('choose_request', deepcopy(request))
        public = {k:request[k] for k in ('stage','system_prompt','user_prompt','response_schema','image_refs')}
        result = self.choose(public)
        self.binding = bind_action_target(request, result)
        self.record('action_binding', deepcopy(self.binding))
        if self.binding['status'] != 'matched':
            self.phase = 'paused'
        return result

    def execute(self, check):
        self._require('execute')
        if not check(deepcopy(self.proposal)):
            raise ValueError('proposal not cleared by the same target/consequence check used in the manual run')
        # Mark pending before delivery. Failure cannot silently replay an action.
        self.phase = 'settle'
        try:
            self.receipt = self.deliver(deepcopy(self.proposal))
        except Exception as exc:
            self.receipt = {'status':'delivery_exception', 'error_type':type(exc).__name__}
            self.record('execution', deepcopy(self.receipt))
            raise
        self.record('execution', deepcopy(self.receipt))
        if self.receipt.get('exit_code') == 0:
            # Return to the screenshot adapter only after the UI settling delay.
            time.sleep(2)
        return self.receipt

    def settle(self, request):
        self._require('settle')
        result = self.model('settle', request)
        self.record('settle', deepcopy(result))
        self.phase = 'choose'
        return result

import identity_templates as templates


def _assemble_local_context(root, records, state, region_ref):
    """Render names and recorded statements, never fabricate outcome summaries."""
    import json
    from pathlib import Path
    region=records[region_ref];obs=state['observation']
    interactive=region_ref in state['interactive_regions']
    supplied=state.get('action_history_supplied',True)
    progress={'registered_controls':len(region['controls']), 'controls_with_delivery':0,
              'controls_with_observed_effect':0, 'controls_with_unresolved_attempts':0,
              'controls_without_record':0 if supplied else None,
              'scope':'registered_region_controls'}
    lines=[f"本轮任务：继续探索「{region['name']}」，选择一个入口。"]
    backend=[];statuses={}
    for cid,c in region['controls'].items():
        attempts=[region['actions'][aid] for aid in c['action_refs']]
        delivered=any(a['delivery']=='executed_receipt_zero' for a in attempts)
        observed=any(a['delivery']=='executed_receipt_zero' and a['result'].get('status')=='observed_effect' for a in attempts)
        unresolved=any(a['delivery']!='executed_receipt_zero' or a['result'].get('exception') in ('external_app','blocking_popup','system_error','unexpected_exit','unclassified','uncertain')
                       or ('exception' not in a['result'] and a['result'].get('status')!='observed_effect') for a in attempts)
        progress['controls_with_delivery']+=delivered
        progress['controls_with_observed_effect']+=observed
        progress['controls_with_unresolved_attempts']+=unresolved
        if supplied and not attempts:progress['controls_without_record']+=1
        summary='未提供动作记录，进度未知' if not supplied else ('所提供图中无动作记录' if not attempts else ('有执行回执' if delivered else '执行未确认'))
        statuses[cid]={'attempts':c['action_refs'],'summary':summary}
        if interactive:
            matching=[v for v in c['observations'] if v['evidence'].get('observation')==obs['id']]
            # Recall admitted history only inside the observed active Region.
            # It remains a visual candidate, not a claim of current visibility.
            appearance=templates.latest(c) or {}
            if matching or appearance:
                v=(matching or c['observations'])[-1]
                backend.append({'id':cid,'name':c['name'],'image':appearance.get('image'),
                                'region_ref':region_ref,'source_image':appearance.get('source_image'),
                                **templates.assessment(appearance),
                                'icon_description':v['icon_description'], 'region_image':templates.image(region),
                                **{k:appearance[k] for k in ('bbox','click_bbox') if k in appearance}})
    ready=interactive and state.get('next_action_mode')=='explore'
    if not ready:lines.append('当前不生成本区块点击请求；等待处理已登记的运行分支。')
    dynamic='\n'.join(lines)
    pr=Path(root)/'遍历prompt'
    stage=json.loads((pr/'流程/02_动作选择.json').read_text())
    fixed=[{'path':v,'text':(pr/v).read_text()} for v in stage['parts']] if ready else []
    schema=json.loads((pr/stage['schema']).read_text()) if ready else None
    return {'stage':stage['stage'] if ready else 'region_history','action_ready':ready,
            'system_prompt':'\n\n'.join(p['text'].strip() for p in fixed),
            'user_prompt':dynamic,'dynamic_prompt':dynamic,'fixed_parts':fixed,
            'response_schema':schema,'response_schema_path':stage['schema'] if ready else None,
            'image_refs':[obs['image']] if obs.get('image') else [],'progress':progress,
            'control_progress':statuses,'backend_candidates':backend if ready else [],
            'source':{'observation':obs['id'],'region':region_ref}}


def contextual_return(action):
    """Historical endpoint is not a promise about the current navigation stack."""
    return action.get('operation')=='back' or action.get('result',{}).get('returns_to_previous') is True


def navigation_description(action):
    description=action.get('result',{}).get('description','')
    if contextual_return(action):
        return '返回或关闭浮层后恢复进入前的界面，目标取决于进入路径；历史观察：'+description
    return description


def shortest_known_path(records, state, target, *, require_control=True):
    """Fewest recorded directed tap edges; first control must be observed now."""
    from collections import deque
    starts=[r for r in state['interactive_regions'] if r in records]
    queue=deque((r, []) for r in starts);seen=set(starts)
    obs=state['observation']
    while queue:
        source,path=queue.popleft()
        if source==target:return path
        region=records[source]
        for edge in region['transitions']:
            dest=edge['target_region'];cid=edge['source_control']
            if cid and any(t.get('status')=='blocked' and t.get('control')==cid for t in region.get('tasks',{}).values()):continue
            action=region['actions'].get(edge['attempt'],{})
            result=action.get('result',{})
            if contextual_return(action):continue
            back=action.get('operation')=='back' and cid is None
            if (dest not in records or dest in seen or (not back and cid not in region['controls'])
                    or action.get('control')!=cid or action.get('operation') not in ('tap','click','back')
                    or len(action.get('executed_steps',[]))>1
                    or action.get('delivery')!='executed_receipt_zero'
                    or result.get('exception', 'none')!='none'
                    or not (result.get('exception')=='none' or result.get('status')=='observed_effect')):
                continue
            if require_control and not path and not back and (cid not in obs['control_refs'] or not any(
                    v['evidence'].get('observation')==obs['id'] and templates.usable(v)
                    for v in region['controls'][cid]['observations'])):
                continue
            step={'source_region':source, 'source_control':cid,
                  'target_region':dest, 'attempt':edge['attempt'], 'operation':action['operation']}
            seen.add(dest);queue.append((dest,path+[step]))
    return None


def render_exploration_tree(records, state, region_ref, *, limit=8):
    """Task-relative view of existing evidence; no new graph or completion state.

    Adapts original region_work.environment_view's focus/collapse semantics to
    the experimental Region records. Navigation is not containment.
    """
    region = records[region_ref]
    if region_ref not in state['interactive_regions']:
        return ''
    current_controls = set(state['observation']['control_refs'])
    supplied = state.get('action_history_supplied', True)
    lines = [region['name']]
    controls = list(region['controls'].items())
    # Prefer actionable appearances and unexplored entries; do not enumerate
    # every other Region's controls to construct this bounded view.
    controls.sort(key=lambda item: (item[0] not in current_controls, bool(item[1]['action_refs'])))
    for cid, control in controls[:limit]:
        attempts = [(aid, region['actions'][aid]) for aid in control['action_refs']]
        if not attempts:
            status = '尚未点击。' if supplied else '未提供动作历史。'
        else:
            last = attempts[-1][1]
            result = last['result']
            operation = {'tap': '点击','click':'点击', 'long_press': '长按', 'swipe': '滑动'}.get(last.get('operation'), '执行动作')
            if last['delivery'] != 'executed_receipt_zero':
                status = operation + '投递未确认。'
            else:
                # Verbatim first-sentence excerpt, not a guessed semantic label.
                description = navigation_description(last) or result.get('evidence') or '未提供结果描述'
                excerpt = description.split('。')[0].split('\n')[0]
                if len(excerpt) > 80:
                    excerpt = excerpt[:80] + '…'
                status = operation + ' → ' + excerpt
                if result.get('exception') == 'uncertain' or result.get('status') == 'uncertain':
                    status += '（结果待确认）'
        lines.append(f"  ├─ {control['name']}：{status}")
        destinations = set()
        for edge in region['transitions']:
            if edge['source_control'] != cid:
                continue
            action = region['actions'].get(edge['attempt'], {})
            result = action.get('result', {})
            target = edge['target_region']
            if (target in records and target not in destinations
                    and action.get('control') == cid
                    and action.get('delivery') == 'executed_receipt_zero'
                    and result.get('exception', 'none') == 'none'
                    and (result.get('exception') == 'none' or result.get('status') == 'observed_effect')):
                destinations.add(target)
                lines.append('  │  已观察跳转 → ' + records[target]['name'] + ('（本次返回落点，依赖进入路径）' if contextual_return(action) else '（详情折叠，不代表探索完成）'))
    if len(controls) > limit:
        lines.append(f'  └─ 另有 {len(controls)-limit} 个已登记控件折叠，不代表探索完成。')
    children = [r['name'] for r in records.values() if r.get('parent_region') == region_ref and r is not region]
    if children:
        lines.append('已登记子区块（独立探索，详情折叠）：' + '、'.join(children[:limit]))
        if len(children) > limit:
            lines.append(f'另有 {len(children)-limit} 个子区块折叠。')
    return '\n'.join(lines)


def assemble_context(root, records, state, region_ref):
    request = _assemble_action_context(root, records, state, region_ref)
    tree = render_exploration_tree(records, state, region_ref)
    request['exploration_tree'] = tree
    if tree:
        request['user_prompt'] = request['dynamic_prompt'] = request['dynamic_prompt'] + '\n\n' + tree
    return request


def _assemble_action_context(root, records, state, region_ref):
    """Keep unfinished work while navigating from the currently observed Regions."""
    request=_assemble_local_context(root,records,state,region_ref)
    if region_ref in state['interactive_regions'] or state.get('next_action_mode')!='explore':
        return request
    import json
    from pathlib import Path
    path=shortest_known_path(records,state,region_ref)
    target=records[region_ref]
    lines=[f"本轮任务：继续「{target['name']}」中尚未完成的探索。", '',
           '当前落点（最近一次更新的观察）：',
           '可交互区块：'+('、'.join(records[r]['name'] for r in state['interactive_regions'] if r in records) or '未确认'),
           f"「{target['name']}」当前不可交互；以下入口为历史记录，请按附图核对。",
           '附图为保存帧，不证明设备此刻状态；执行前仍需核对。', '',
           f"待继续探索区块：{target['name']}", target['description']]
    lines.extend(['当前观察说明：'+str(state.get('observation',{}).get('foreground',{}).get('description','')),
                  '先判断当前前景与目标的关系：包含目标入口或属于到达目标的中间步骤时，操作其中的入口；只有前景与目标无关且妨碍下一步时才关闭或返回。菜单接管输入不等于阻挡探索。正例：目标在设置子菜单中，先操作菜单内的设置入口；反例：刚打开通往目标的菜单，就因为目标区块尚未出现而关闭菜单。历史路径入口当前不可见时，可先切换相关标签或自行寻找其他路径，不必关闭正常编辑窗口。', '', '前往待继续区块的路径：'])
    lines.append('最近已执行动作及实际结果见共同地图的区块控件历史及登记顺序；若已经反复打开、关闭同一入口且未接近目标，不再原样重复。选择有新依据的其他导航方式；没有新办法时用none说明循环与缺口。历史一次未跳转不证明入口永久无效。')
    if path:
        lines.append(f'最短已知路径（{len(path)} 步）：')
        for i,edge in enumerate(path,1):
            owner=records[edge['source_region']]
            operation='系统返回' if edge['operation']=='back' else '点击「'+owner['controls'][edge['source_control']]['name']+'」'
            lines.append(f"{i}. {owner['name']} → {operation} → {records[edge['target_region']]['name']}")
        lines.append('依据：已有执行和落点记录；这是已知图内的最短路径，仅供参考，不保证全局最短或此刻可用。')
        if len(path)>1:
            lines.extend(['', '后续入口参考（可寻找直接到达的机会）：'])
            for edge in path[1:]:
                if edge['operation'] not in ('click','tap'):continue
                owner=records[edge['source_region']];control=owner['controls'][edge['source_control']]
                described=next((o for o in reversed(control.get('observations',[])) if o.get('icon_description') or o.get('text')), {})
                appearance=described.get('icon_description') or described.get('text','')
                current=(edge['source_region'] in state['interactive_regions'] and edge['source_control'] in state['observation'].get('control_refs',[]))
                status='本轮已有定位，仍需核对当前截图' if current else '历史入口，尚未确认当前可操作'
                if templates.evidence_limit(described):status+='；该次视觉身份依据因纯色模板不足，不能据原描述确认可见或可操作'
                lines.append(f"- 「{control['name']}」｜所属：{owner['name']}｜已知去向：{records[edge['target_region']]['name']}｜{status}"+(f"｜外观：{appearance}" if appearance else ''))
            lines.append('后续入口不是必做顺序；当前截图中目标位置与作用可靠时可直接选择，不要求已登记。只看见相似图标、无法确认对象或作用时，用none请求发现，不猜坐标。')

    else:
        lines.append('当前图中尚未记录到达路径；请根据截图自行寻找入口，执行后再确认实际落点。')
    visible=[rid for rid in state['interactive_regions'] if rid in records]
    if visible:
        owner=path[0]['source_region'] if path else visible[0]
        current=_assemble_local_context(root,records,state,owner)
        request.update({k:current[k] for k in ('stage','action_ready','fixed_parts','system_prompt','response_schema','response_schema_path')})
        request['backend_candidates']=[{**c,'region_ref':rid} for rid in visible
            for c in _assemble_local_context(root,records,state,rid)['backend_candidates']]
        request['source']['region']=owner
        request['allow_back']=True
        request['region_image']=templates.image(records[owner])
        request['region_image_assessment']=templates.assessment(templates.latest(records[owner]) or {})
        request['region_target']=records[owner]['name']
        request['allow_scroll']=True
        request['allow_input']=True
        request['source']['return_to']=region_ref  # Intended goal, never a claimed landing.
        request['navigation_advice']=True
        pr=Path(root)/'遍历prompt';part='动作/探索导航路线.prompt'
        request['fixed_parts'].append({'path':part,'text':(pr/part).read_text()})
        request['system_prompt']='\n\n'.join(p['text'].strip() for p in request['fixed_parts'])
        lines.append('当前区块内的登记入口候选（含历史记录，不保证当前可见或可操作；以本图及下方匹配位置核对）：'+('；'.join(records[c['region_ref']]['name']+'：'+c['name'] for c in request['backend_candidates']) or '暂无登记候选，可结合截图判断系统返回或等待'))
        lines.append('本轮只寻找通往目标区块的动作；不要为了再次验证已知控件效果而偏离导航目标。没有已知回程时，可结合截图尝试返回，不能把预览、选择等局部状态变化当作通往其他区块的路径。')

    lines.append('无动作记录不等于功能未完成；已有尝试也不代表区块探索完成。')
    request['navigation_path']=path
    request['source']['working_region']=region_ref
    request['user_prompt']=request['dynamic_prompt']='\n'.join(lines)
    import page_history
    return page_history.attach(request,records,state)


def assemble_region_choice(root, graph, observation_ref, region_ref):
    """Saved-graph replay adapter; uses the same record schema and renderer."""
    state=graph_state(graph,observation_ref)
    if region_ref not in state['interactive_regions']:
        raise ValueError('working Region is not a current observation candidate')
    return assemble_context(root,region_records(graph,observation_ref),state,region_ref)


def resolve_action_operations(records, run):
    from action_evidence import resolve_operations
    resolve_operations(records, run)


def assemble_current_context(root, run, region_ref=None, task_ref=None):
    """Public request entry; work selection is owned by traversal_scheduler."""
    from action_proposer import request_from_run
    return request_from_run(root, run, region_ref, task_ref)


# Stable import surface; implementations live in the responsibility modules above.
from region_evidence import (region_transitions, new_region, region_observation, control_observation, control_name, action_record, index_actions, region_records, graph_state)
from action_binding import (bind_action_target, _bind_action_target)
