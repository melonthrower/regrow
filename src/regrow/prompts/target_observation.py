from regrow.records.control_knowledge import parameters
"""Shared read-only target observations for action selection and correction."""
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from regrow.recognition import identity_templates as templates

def describe(control, observation):
    rows = observation_history(control)
    matching = [v for v in rows if observation and v.get('evidence', {}).get('observation') == observation]
    row = (matching or rows or [{}])[-1]
    prior = rows[:rows.index(row)] if row in rows else []
    old = next((v for v in reversed(prior) if v.get('icon_description')), {})
    source = row.get('evidence', {})
    result = {'观察来源': source.get('observation') or source.get('source_call', ''), '登记外观': row.get('icon_description', ''), '功能推测（未验证）': row.get('possible_operation', ''), '功能疑问': row.get('uncertainty', ''), '历史外观参考': old.get('icon_description', '')}
    if row.get('visual_only'):
        result['观察类型'] = '图片定位'
    from regrow.records.control_history_context import last_reported
    for (field, label) in (('icon_description', '登记外观'), ('possible_operation', '功能推测（未验证）'), ('uncertainty', '功能疑问')):
        if field not in row:
            prior_field = last_reported(control, field)
            if field in prior_field:
                result[label] = prior_field[field]
                result[label + '来源'] = prior_field.get('evidence', {})
    if templates.evidence_limit(row):
        result['视觉依据限定'] = templates.evidence_limit(row)
    if templates.evidence_limit(old):
        result['历史外观参考限定'] = templates.evidence_limit(old)
    return result

def handoff(records, state, run=None):
    """Carry observation gaps; action evidence is owned by page_history."""
    observation = state.get('observation') or {}
    summary = state.get('handoff_summary', '')
    gaps = observation.get('uncertainties', [])
    if not summary and (not gaps):
        return {}
    return {'来源': observation.get('id', ''), '交接说明': summary, '未确认事项': gaps}

def attach_handoff(request, records, state, run=None):
    if not request.get('action_ready'):
        return request
    context = handoff(records, state, run)
    if context:
        request['observation_handoff'] = context
        return render_handoff(request)
    return request

def compact_handoff(context, history):
    handoff = history.get('handoff')
    if handoff and context.get('交接说明') == handoff['summary'] and (context.get('未确认事项') == handoff['uncertainties']):
        from regrow.records import page_history as page_history
        return {'来源': context['来源'], '交接与未确认事项': '见' + page_history.reference(history, handoff['attempt'])}
    return context

def render_handoff(request):
    context = request.get('observation_handoff')
    if not context:
        return request
    history = request.get('page_context', {}).get('history', {})
    supplied = {event.get('观察') for event in history.get('events', {}).values()}
    supplied.update((event.get('该次更新交接') for event in history.get('events', {}).values()))
    from regrow.prompts.prompt_material import assign
    value = {}
    if context.get('交接说明') and context['交接说明'] not in supplied:
        value['最近观察'] = context['交接说明']
    supplied_gaps = {gap for event in history.get('events', {}).values()
                     for gap in event.get('该次更新未确认事项', [])}
    gaps = [gap for gap in context.get('未确认事项', []) if gap not in supplied_gaps]
    if gaps:
        value['页面观察未确认事项'] = gaps
    return assign(request, value, remove=('上步观察交接', '最近观察', '未确认事项', '页面观察未确认事项'))

def attach(request, records):
    if not request.get('action_ready'):
        return request
    source = request.get('source', {})
    region = records.get(source.get('region'), {})
    for candidate in request.get('backend_candidates', []):
        owner = records.get(candidate.get('region_ref', source.get('region')), region)
        control = owned_controls(owner).get(candidate['id'])
        if control is None:
            continue
        candidate['target_observation'] = describe(control, source.get('observation'))
        candidate['region_name'] = owner.get('name', '')
        from regrow.records.control_history_context import known_information
        candidate['knowledge'] = known_information(control, parameters=False)
        if candidate['id'] == source.get('task_control') and parameters(control):
            candidate['constraints'] = parameters(control)
    return refresh(request)

def refresh(request):
    """Rebuild positions after a frame replacement, including the rendered table."""
    from regrow.records import page_context as page_context
    page_context.refresh(request)
    if request.get('stage') == 'step_correction':
        return request
    from regrow.recognition import matching as choices
    request = choices.prepare(request)
    from regrow.traversal.action_binding import disclose_candidates
    return disclose_candidates(render(request))

def render(request):
    """One identity/function list, also used for exact operation binding."""
    if not request.get('action_ready'):
        return request
    from regrow.traversal.action_binding import candidate_rows
    from regrow.prompts.history_disclosure import knowledge_text
    from regrow.prompts.history_disclosure import readable
    from regrow.prompts.prompt_material import assign
    view = request.get('page_context', {})
    known = {}
    region_info = {}

    def collect(nodes):
        for node in nodes:
            region_info[node['ref']] = node
            for control in node.get('controls', []):
                known[node['ref'], control['ref']] = control.get('knowledge', {})
            collect(node.get('children', []))
    collect(view.get('current_tree', []))
    groups = {rid: {'name': node['name'], 'lines': [], 'knowledge': node.get('knowledge', {})} for (rid, node) in region_info.items()}
    for row in candidate_rows(request):
        item = row['candidate']
        rid = item.get('region_ref', request['source']['region'])
        cid = item['id']
        group = groups.setdefault(rid, {'name': item.get('region_name', rid), 'lines': []})
        lines = group['lines']
        lines.append('  - ' + row['target'] + ' ' + row['name'])
        facts = known.get((rid, cid)) or {k: item[k] for k in ('knowledge', 'constraints') if item.get(k)}
        if facts:
            lines.extend(('    ' + line for line in knowledge_text(facts).splitlines()))
        observed = item.get('target_observation', {})
        appearance = item.get('icon_description')
        if appearance:
            lines.append('    外观：' + appearance)
        for field in ('功能疑问', '视觉依据限定'):
            if observed.get(field):
                lines.append('    ' + field + '：' + readable(observed[field], 1))
    text = []
    for (rid, group) in groups.items():
        text.append('- ' + rid + ' ' + group['name'])
        if group.get('knowledge'):
            text.extend(('  ' + line for line in knowledge_text(group['knowledge']).splitlines()))
        text.extend(group['lines'])
    request.pop('target_observations', None)
    return assign(request, {'相关控件': '\n'.join(text)}, remove=('目标控件记录', '可登记动作身份', '当前前景的相关外层身份候选', '最近登记的任务入口'))
