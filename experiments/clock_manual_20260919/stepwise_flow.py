"""One-step sequencing and a read-only Region-edge view of real evidence.

Adapters supply the request, model transport, GUI delivery and persistence.
No automatic loop, Page identity, extra reviewer or model retry is inserted.
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

    def choose_from_run(self, root, run, region_ref):
        self._require('choose')
        request=assemble_current_context(root,run,region_ref)
        if not request['action_ready']:
            raise ValueError('current Region is not ready for an exploration action')
        self.record('choose_request',deepcopy(request))
        public={k:request[k] for k in ('stage','system_prompt','user_prompt','response_schema','image_refs')}
        result=self.choose(public)
        self.binding=bind_action_target(request,result)
        self.record('action_binding',deepcopy(self.binding))
        if self.binding['status']!='matched':self.phase='paused'
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


def region_transitions(graph):
    """Project observed endpoints; do not infer causal effects or reverse paths.

    One action may reach multiple current Region candidates. Background changes
    remain annotations, never extra transitions. Source evidence stays immutable.
    """
    regions = {r['id'] for r in graph['regions']}
    controls = {c['id']:c for c in graph['controls']}
    result = []
    for edge in graph['action_edges']:
        if (edge.get('delivery') != 'executed_receipt_zero'
                or edge.get('model_result', {}).get('status') != 'observed_effect'):
            continue
        source, control = edge['source_region'], edge['source_control']
        if source not in regions or controls.get(control, {}).get('owner_ref') != source:
            raise ValueError('transition source is not the recorded control owner')
        for target in dict.fromkeys(edge['after_interactive_region_proposals']):
            if target not in regions:
                raise ValueError('unknown target Region')
            result.append({
                'source_region':source, 'source_control':control,
                'target_region':target, 'attempt':edge['attempt'],
                'relation':'reaches_observed_interactive_candidate',
                'before_observation':edge['before_observation'],
                'after_observation':edge['after_observation'],
                'before_image':edge['before_image'], 'after_image':edge['after_image'],
                'selection_call':edge['selection_call'], 'result_call':edge['result_call'],
                'interaction_scope_verified':edge.get('interaction_scope_verified', False),
                'region_changes':deepcopy(edge.get('region_changes', [])),
                'status':'derived_from_executed_action_and_model_observation',
            })
    return result


def new_region(ref, name, description=''):
    return {'id':ref, 'name':name, 'description':description, 'parent_region':None,
            'observations':[], 'controls':{}, 'functions':{}, 'actions':{},
            'transitions':[], 'reached_by':[]}


def region_observation(proposal, evidence, image=None):
    return {'description':proposal.get('description',''), 'reason':proposal.get('reason',''),
            'controls_complete':proposal.get('controls_complete',False),
            'image':image, **templates.assessment(proposal), 'evidence':deepcopy(evidence)}


def control_observation(proposal, evidence, image=None, icon_image=None):
    return {'text':proposal.get('text',''), 'icon_description':proposal.get('icon_appearance',''),
            'state':proposal.get('state',''), 'possible_operation':proposal.get('possible_operation',''),
            'uncertainty':proposal.get('uncertainty',''), **templates.assessment(proposal), 'image':image, 'icon_image':icon_image,
            'bbox':deepcopy(proposal.get('bbox')),
            **({'click_bbox':deepcopy(proposal['click_bbox'])} if 'click_bbox' in proposal else {}),
            'evidence':deepcopy(evidence)}


def control_name(proposal):
    return proposal.get('name') or proposal.get('text') or proposal.get('icon_appearance') or '未命名控件'


def action_record(edge):
    # Preserve legacy assessments as reported; never invent exception=none.
    evidence = {k:deepcopy(edge[k]) for k in ('before_observation','after_observation',
                'before_image','after_image','selection_call','result_call') if k in edge}
    evidence['execution_dir'] = f"action_attempts/{edge['attempt']}"
    return {'control':edge['source_control'], 'delivery':edge.get('delivery','unconfirmed'),
            'result':deepcopy(edge.get('model_result',{})),
            'region_changes':[{'region':v['region_ref'], **{k:deepcopy(x) for k,x in v.items() if k!='region_ref'}}
                              for v in edge.get('region_changes',[])],
            'interactive_regions':deepcopy(edge.get('after_interactive_region_proposals',[])),
            'evidence':evidence}


def index_actions(records):
    for r in records.values():
        for cid,c in r['controls'].items():
            c['action_refs']=[aid for aid,a in r['actions'].items() if a['control']==cid]


def region_records(graph, observation_ref=None):
    """Import saved discovery evidence into the same records used by updates.

    A cutoff is for historical replay only; the maintained reader uses committed
    snapshots. No future action outcomes may leak into a replayed earlier frame.
    """
    observations=graph.get('observations',[])
    positions={o['id']:i for i,o in enumerate(observations)}
    limit=positions[observation_ref] if observation_ref else len(observations)-1
    included=observations[:limit+1]
    known={ref for o in included for ref in o.get('region_refs',[])}
    records={}
    for raw in graph['regions']:
        ref=raw['id']
        if observation_ref and ref not in known:continue
        prop=raw.get('proposal',{})
        r=new_region(ref,prop.get('name',ref),prop.get('description',''))
        evidence={k:raw[k] for k in ('observation','source_call','source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation']=next((o['id'] for o in included if ref in o.get('region_refs',[])),None)
        r['observations'].append(region_observation(prop,evidence,raw.get('crop')))
        observed=next((o for o in included if o['id']==evidence['observation']),{})
        r['observations'][-1]['source_image']=observed.get('frame')
        records[ref]=r
    for raw in graph['regions']:
        if raw['id'] not in records:continue
        parent=raw.get('proposal',{}).get('parent_index')
        if parent is not None:
            siblings=[v for v in graph['regions'] if v.get('source_call')==raw.get('source_call')]
            if not 0<=parent<len(siblings):raise ValueError('invalid discovery parent index')
            records[raw['id']]['parent_region']=siblings[parent]['id']
    for raw in graph['controls']:
        owner=raw['owner_ref'];ref=raw['id']
        if owner not in records:continue
        if observation_ref and not any(ref in o.get('control_refs',[]) for o in included):continue
        evidence={k:raw[k] for k in ('observation','source_call','source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation']=next((o['id'] for o in included if ref in o.get('control_refs',[])),None)
        prop=raw.get('proposal',{})
        records[owner]['controls'][ref]={'name':control_name(prop),
            'observations':[control_observation(prop,evidence,raw.get('control_crop'),raw.get('icon_crop'))], 'action_refs':[]}
        observed=next((o for o in included if o['id']==evidence['observation']),{})
        records[owner]['controls'][ref]['observations'][-1]['source_image']=observed.get('frame')
    for edge in graph.get('action_edges') or []:
        source,control=edge['source_region'],edge['source_control']
        before,after=edge.get('before_observation'),edge.get('after_observation')
        if before not in positions or (after is not None and after not in positions):
            raise ValueError('action references unknown observation')
        if (after is not None and positions[after]>limit) or (after is None and positions[before]>=limit):continue
        if source not in records or control not in records[source]['controls']:
            raise ValueError('action references unknown control or inconsistent Region owner')
        if any(t not in records for t in edge.get('after_interactive_region_proposals',[])):
            raise ValueError('unknown target Region')
        records[source]['actions'][edge['attempt']]=action_record(edge)
        if edge.get('delivery')=='executed_receipt_zero' and edge.get('model_result',{}).get('status')=='observed_effect':
            before_regions=observations[positions[before]].get('region_refs',[])
            changed={v['region_ref'] for v in edge.get('region_changes',[]) if v['state']=='changed_interactive'}
            for target in dict.fromkeys(edge.get('after_interactive_region_proposals',[])):
                if target in before_regions and target not in changed:continue
                records[source]['transitions'].append({'source_control':control,'target_region':target,
                    'attempt':edge['attempt'],'relation':'observed_interactive_candidate'})
                records[target]['reached_by'].append({'source_region':source,'source_control':control,'attempt':edge['attempt']})
    index_actions(records)
    return records


def graph_state(graph, observation_ref=None):
    observations=graph['observations']
    obs=next(o for o in observations if o['id']==observation_ref) if observation_ref else observations[-1]
    return {'interactive_regions':obs.get('region_refs',[]), 'next_action_mode':'explore',
            'observation':{'id':obs['id'],'image':obs.get('frame'),
                'control_refs':obs.get('control_refs',[]),'foreground':obs.get('foreground',{}),
                'uncertainties':obs.get('uncertainties',[])},
            'action_history_supplied':graph.get('action_edges') is not None}


def _assemble_local_context(root, records, state, region_ref):
    """Render names and recorded statements, never fabricate outcome summaries."""
    import json
    from pathlib import Path
    region=records[region_ref];obs=state['observation']
    interactive=region_ref in state['interactive_regions']
    visible=set(obs['control_refs']) if interactive else set()
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
        if cid in visible:
            matching=[v for v in c['observations'] if v['evidence'].get('observation')==obs['id']]
            # Current visibility is required; a historical template still needs current matching.
            if matching:
                v=matching[-1]
                appearance=templates.latest(c) or {}
                backend.append({'id':cid,'name':c['name'],'image':appearance.get('image'),
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
    recent={}
    for owner in records.values():
        for attempt,action in owner.get('actions',{}).items():
            if action.get('delivery')!='executed_receipt_zero':continue
            target_name=owner.get('controls',{}).get(action.get('control'),{}).get('name') or action.get('association',{}).get('target') or owner['name']
            recent[attempt]=f"{owner['name']} / {target_name}：{action.get('result',{}).get('description','结果未确认')}"
    if recent:
        lines.extend(['最近已执行动作及实际结果（按执行顺序）：',*[recent[k] for k in sorted(recent)[-6:]],
                      '若这些动作已经反复打开、关闭同一入口且未接近目标，不再原样重复。选择有新依据的其他导航方式；没有新办法时用none说明循环与缺口。历史一次未跳转仅说明那次观察，不证明入口永久无效。'])
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
                appearance=next((o.get('icon_description') or o.get('text') for o in reversed(control.get('observations',[])) if o.get('icon_description') or o.get('text')), '')
                current=(edge['source_region'] in state['interactive_regions'] and edge['source_control'] in state['observation'].get('control_refs',[]))
                status='本轮已有定位，仍需核对当前截图' if current else '历史入口，尚未确认当前可操作'
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
        lines.append('当前可选入口：'+('；'.join(records[c['region_ref']]['name']+'：'+c['name'] for c in request['backend_candidates']) or '暂无已定位控件，可结合截图判断系统返回或等待'))
        for candidate in request['backend_candidates']:
            region=records[candidate['region_ref']];control=region['controls'][candidate['id']]
            results=[region['actions'][a].get('result',{}).get('description')
                     for a in control.get('action_refs',[]) if a in region['actions']]
            results=list(dict.fromkeys(r for r in results if r))
            if results:lines.append('「'+candidate['name']+'」已有观察：'+'；'.join(results[-2:]))
        lines.append('本轮只寻找通往目标区块的动作；不要为了再次验证已知控件效果而偏离导航目标。没有已知回程时，可结合截图尝试返回，不能把预览、选择等局部状态变化当作通往其他区块的路径。')

    lines.append('无动作记录不等于功能未完成；已有尝试也不代表区块探索完成。')
    request['navigation_path']=path
    request['source']['working_region']=region_ref
    request['user_prompt']=request['dynamic_prompt']='\n'.join(lines)
    return request


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
    import json
    from pathlib import Path
    run=Path(run);pointer=json.loads((run/'knowledge_current.json').read_text())
    snapshot=run/pointer['snapshot']
    source=json.loads((snapshot/'source.json').read_text())
    if source.get('record_format')!='region_image_knowledge':
        raise ValueError('historical record layout; rebuild saved evidence before reading current knowledge')
    records={p.parent.name:json.loads(p.read_text()) for p in (snapshot/'regions').glob('*/region.json')}
    state=json.loads((snapshot/'runtime_state.json').read_text())
    if state.get('next_action_mode')=='discover':raise ValueError('discovery required before action context')
    if region_ref is None:region_ref=state['working_region']
    if task_ref:
        task=records.get(task_ref['region'],{}).get('tasks',{}).get(task_ref['name'])
        if not task or task.get('status')!='pending':raise ValueError('原动作任务已不可继续，不能切换成其他任务')
        state['active_task']=dict(task_ref)
        region_ref=task_ref['region']
    if (snapshot/'recovery.json').exists():
        recovery=json.loads((snapshot/'recovery.json').read_text())
        if recovery['actions']:state['recovery_arrival']=recovery['actions'][-1]
    resolve_action_operations(records,run)
    # Resolve references only in this in-memory request, never rewrite knowledge.
    for ref,r in records.items():
        for v in r['observations']:
            if v.get('image'):v['image']=str((snapshot/f'regions/{ref}'/v['image']).resolve())
        for c in r['controls'].values():
            for v in c['observations']:
                if v['image']:v['image']=str((snapshot/f'regions/{ref}'/v['image']).resolve())
    if state['observation'].get('image'):
        state['observation']['image']=str((run/state['observation']['image']).resolve())
    import importlib.util
    if state.get('visual_navigation'):
        nav_spec=importlib.util.spec_from_file_location('visual_backtrack',Path(__file__).with_name('visual_backtrack.py'))
        navigation=importlib.util.module_from_spec(nav_spec);nav_spec.loader.exec_module(navigation)
        navigation.project(records,state)
    result=assemble_context(root,records,state,region_ref)
    import importlib.util
    spec=importlib.util.spec_from_file_location('region_tasks',Path(__file__).with_name('region_tasks.py'))
    tasks=importlib.util.module_from_spec(spec);spec.loader.exec_module(tasks)
    result=tasks.attach(root,records,state,region_ref,result)
    tasks.helper('target_observation').attach(result,records)
    tasks.helper('target_observation').attach_handoff(result,records,state,run)
    if state.get('navigation_handoff') and result.get('action_ready'):
        result['user_prompt']=result['dynamic_prompt']=result['user_prompt']+'\n\n自动回溯交接：'+json.dumps(state['navigation_handoff'],ensure_ascii=False)
    result['source']['snapshot']=pointer['snapshot']
    return result


def bind_action_target(request, proposal):
    binding=_bind_action_target(request,proposal)
    source=request.get('source',{})
    if binding.get('status')=='matched' and request.get('preparation_allowed') and source.get('task_type')=='single_action':
        expected={'tap':'click'}.get(source.get('task_action'),source.get('task_action'))
        action={'tap':'click'}.get(proposal.get('action'),proposal.get('action'))
        binding['preparatory_action']=(binding.get('control_ref')!=source.get('task_control') or action!=expected)
    return binding


def _bind_action_target(request, proposal):
    """Conservative linkage to recorded candidates, not a live identity verifier.

    Never guess nearest controls or enlarge text boxes into unknown row bounds.
    Low-confidence image evidence is advisory when it agrees with the model position.
    """
    base = {'region_ref':request['source']['region'],
            'observation_ref':request['source']['observation'], 'control_ref':None,
            'working_region':request['source'].get('working_region',request['source']['region'])}
    for key in ('task_name','task_region','task_type','return_to'):
        if key in request['source']:base[key]=request['source'][key]
    if proposal.get('action') == 'back':
        if proposal.get('x') is None and proposal.get('y') is None:
            return {**base,'status':'matched','basis':'region-owned return action; verify foreground before delivery'}
        return {**base,'status':'unresolved','reason':'back not allowed for this task'}
    if proposal.get('action') in ('key_press','hotkey'):
        return {**base,'status':'matched','basis':'Region-owned keyboard action; current focus must be observed'}
    if proposal.get('action') == 'wait':
        return {**base,'status':'matched','basis':'Region-owned observation wait'}
    if proposal.get('action') == 'none':
        return {**base, 'status':'no_action'}
    if proposal.get('action')=='scroll' and request.get('platform')=='desktop':
        from desktop_scroll import bind
        return {**base,**bind(request,proposal)}
    if proposal.get('action') in ('hover','drag') or (proposal.get('action')=='scroll' and request.get('navigation_advice')):
        from PIL import Image
        from pathlib import Path
        frames=request.get('image_refs',[])
        if len(frames)!=1 or not Path(frames[0]).is_file():
            return {**base,'status':'unresolved','reason':'current screenshot is missing'}
        coords=[proposal.get(k) for k in ('x','y','end_x','end_y')]
        if proposal.get('action')=='hover':coords=coords[:2]+coords[:2]
        if any(type(v) is not int for v in coords):
            return {**base,'status':'unresolved','reason':'scroll needs integer start and end coordinates'}
        with Image.open(frames[0]) as frame:width,height=frame.size
        x,y,ex,ey=coords
        if not (0<=x<width and 0<=y<height and ((proposal.get('action')=='scroll' and request.get('platform')=='desktop') or (0<=ex<width and 0<=ey<height))) or ((x,y)==(ex,ey) and proposal.get('action')!='hover'):
            return {**base,'status':'unresolved','reason':'pointer coordinates outside screenshot or no displacement'}
        if proposal.get('action')=='scroll':
            return {**base,'status':'matched','model_grounded':True,'basis':'navigation scroll uses model coordinates in current screenshot'}
        # Hover and drag still need the same target association as a click.
    if proposal.get('action')=='scroll':
        if not request.get('allow_scroll'):
            return {**base,'status':'unresolved','reason':'scroll is outside the routed task'}
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('scroll_match',Path(__file__).with_name('image_match.py'))
        matcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(matcher)
        template=request.get('region_image');frames=request.get('image_refs',[])
        if not templates.usable({'image':template,**request.get('region_image_assessment',{})}) or len(frames)!=1:return {**base,'status':'unresolved','reason':'Region identity template missing or not admitted'}
        match=matcher.locate(template,frames[0])
        coords=[proposal.get(k) for k in ('x','y','end_x','end_y')]
        if not match['accepted'] or any(type(v) is not int for v in coords):return {**base,'status':'unresolved','reason':'scroll Region not localized'}
        left,top,right,bottom=match['box'];x,y,ex,ey=coords
        desktop=request.get('platform')=='desktop'
        endpoints_ok=(left<=x<right and top<=y<bottom) and (desktop or (left<=ex<right and top<=ey<bottom))
        if not endpoints_ok or (x,y)==(ex,ey):
            return {**base,'status':'unresolved','reason':'swipe leaves Region or has no displacement'}
        return {**base,'status':'matched','basis':'desktop wheel origin lies in matched Region; endpoint describes wheel direction' if desktop else 'both swipe endpoints lie in matched Region'}
    if proposal.get('action')=='input_text' and (not (request.get('allow_input') or request.get('navigation_advice')) or not isinstance(proposal.get('text'),str)):
        return {**base,'status':'unresolved','reason':'input is outside the routed task'}
    if proposal.get('action') not in ('tap','click','double_click','long_press','right_click','input_text','hover','drag'):
        return {**base, 'status':'unresolved', 'reason':'unsupported operation'}
    x, y = proposal.get('x'), proposal.get('y')
    if any(isinstance(v, bool) or not isinstance(v, (int,float)) for v in (x,y)):
        return {**base, 'status':'unresolved', 'reason':'missing position'}
    target = str(proposal.get('target','')).strip().casefold()
    from pathlib import Path
    import importlib.util
    spec=importlib.util.spec_from_file_location('stepwise_image_match',Path(__file__).with_name('visual_choices.py'))
    matcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(matcher)
    frames=request.get('image_refs',[])
    if len(frames)!=1 or not Path(frames[0]).is_file():
        return {**base,'status':'unresolved','reason':'current screenshot is missing'}
    from PIL import Image
    with Image.open(frames[0]) as frame:width,height=frame.size
    if not (0<=x<width and 0<=y<height):return {**base,'status':'unresolved','reason':'coordinates outside screenshot'}
    hits=[];selected={};model_grounded=set();diagnostics=[]
    named=[c for c in request['backend_candidates'] if target and target in
           [str(c.get(k,'')).strip().casefold() for k in ('name','icon_description')]]
    point_binding=bool(target) and not named and proposal.get('action') in ('tap','click','double_click','long_press','right_click','hover','drag')
    for c in (request['backend_candidates'] if point_binding else named):
        if not c.get('image') or not Path(c['image']).is_file():
            diagnostics.append(c['name']+'：缺少记录图片');continue
        match=matcher.match_control(c,frames[0])
        diagnostics.append(c['name']+'：候选范围'+str(match.get('box'))+'，模型位置'+str((x,y))+'，图片判断'+str(match.get('reason',match.get('accepted'))))
        if not match['accepted']:
            if point_binding:continue  # A wording fallback must not lower visual confidence.
            disclosed=request.get('visual_choices',{}).get(c['id'],[])
            alternatives=[v for v in match.get('candidates',[]) if any(v['box']==d['box'] for d in disclosed)
                          and v['box'][0]<=x<v['box'][2] and v['box'][1]<=y<v['box'][3]]
            if len(alternatives)==1 and str(proposal.get('reason','')).strip():
                hits.append(c);selected[c['id']]=alternatives[0]
            elif not match.get('candidates') and match.get('box') and str(proposal.get('reason','')).strip():
                left,top,right,bottom=match['box']
                if left<=x<right and top<=y<bottom:
                    hits.append(c);model_grounded.add(c['id'])
            continue
        left,top,right,bottom=match['box']
        if left<=x<right and top<=y<bottom:hits.append(c)
    if len(hits)==1:
        base['region_ref']=hits[0].get('region_ref',base['region_ref'])
        if hits[0]['id'] in model_grounded:
            return {**base,'status':'matched','control_ref':hits[0]['id'],'model_grounded':True,
                    'basis':'model position agrees with low-confidence image candidate; no visual contradiction established'}
        if hits[0]['id'] in selected:
            return {**base,'status':'matched','control_ref':hits[0]['id'],'visual_choice':selected[hits[0]['id']],
                    'basis':'model selected one disclosed appearance candidate; current image reconfirmed its bounds'}
        return {**base,'status':'matched','control_ref':hits[0]['id'],
                'basis':'unique strong visual match at model point; target wording differed' if point_binding else 'exact description and unique crop match in supplied frame; live check still required'}
    reason=('当前候选表没有目标 '+str(proposal.get('target')) if not diagnostics else '多个登记对象同时符合，需区分身份' if len(hits)>1 else '目标未能对应：'+'；'.join(diagnostics))
    if not target:return {**base,'status':'unresolved','reason':'missing target description'}
    return {**base,'status':'matched','model_grounded':True,
            'basis':'execute model coordinates; recorded control association remains unconfirmed',
            'association':{'status':'unconfirmed','target':proposal['target'],'x':x,'y':y,
                           'candidates':[{'region':c.get('region_ref',base['region_ref']),'control':c['id']} for c in named],
                           'reason':reason}}
