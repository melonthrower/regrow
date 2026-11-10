"""Bind registered refs; route descriptions to registration before execution."""

def bind_action_target(request, proposal, *, records=None):
    binding = _bind_action_target(request, proposal, records=records)
    source = request.get('source', {})
    if binding.get('status') == 'matched' and request.get('preparation_allowed') and source.get('task_name'):
        binding['preparatory_action'] = binding.get('control_ref') != source.get('task_control') or binding.get('region_ref') != source.get('completion_region', source.get('region'))
    return binding

def _bind_action_target(request, proposal, *, records=None):
    """Associate the reported target without inferring identity from its position."""
    base = {'region_ref': request['source']['region'], 'observation_ref': request['source']['observation'], 'control_ref': None, 'working_region': request['source'].get('working_region', request['source']['region'])}
    for key in ('task_name', 'task_region', 'task_type', 'return_to'):
        if key in request['source']:
            base[key] = request['source'][key]
    from regrow.recognition.control_references import recorded_target
    reference = recorded_target(records, proposal.get('target')) if proposal.get('action') != 'none' else None
    if reference:
        owners = reference['regions']
        source = request.get('source', {})
        preferred = [source.get(key) for key in ('working_region', 'region', 'completion_region', 'task_region')]
        if reference['kind'] == 'control':
            from regrow.records.object_store import control_record, observation_history
            control = control_record(records, reference['ref'])
            preferred += [row.get('evidence', {}).get('region') for row in reversed(observation_history(control))]
        owner = next((rid for rid in preferred if rid in owners), owners[0])
        base.update(region_ref=owner,
                    control_ref=reference['ref'] if reference['kind'] == 'control' else None,
                    reference_bound=True, model_grounded=True,
                    basis='explicit registered object ref; ownership from records')
        if reference['kind'] == 'region':
            base['association'] = {'status': 'confirmed', 'basis': 'explicit_ref', 'region': owner}
    if proposal.get('action') == 'back':
        if proposal.get('x') is None and proposal.get('y') is None:
            return {**base, 'status': 'matched', 'basis': base.get('basis', 'region-owned return action; verify foreground before delivery')}
        return {**base, 'status': 'unresolved', 'reason': 'back not allowed for this task'}
    if proposal.get('action') in ('key_press', 'hotkey'):
        return {**base, 'status': 'matched', 'basis': base.get('basis', 'Region-owned keyboard action; current focus must be observed')}
    if proposal.get('action') == 'wait':
        return {**base, 'status': 'matched', 'basis': base.get('basis', 'Region-owned observation wait')}
    if proposal.get('action') == 'none':
        return {**base, 'status': 'no_action'}
    if proposal.get('action') == 'scroll':
        from regrow.traversal import region_scroll as region_scroll
        return region_scroll.bind(request, proposal, base)
    if not reference:
        return {**base, 'status': 'matched', 'model_grounded': True,
                'association': {'status': 'unconfirmed', 'target': proposal.get('target'),
                                'reason': '操作目标尚无准确ref；先完成当前对象登记，再按ref选择动作。'},
                'basis': 'registration required; no executable object binding'}
    if proposal.get('action') in ('hover', 'drag'):
        from PIL import Image
        from pathlib import Path
        frames = request.get('image_refs', [])
        if len(frames) != 1 or not Path(frames[0]).is_file():
            return {**base, 'status': 'unresolved', 'reason': 'current screenshot is missing'}
        coords = [proposal.get(k) for k in ('x', 'y', 'end_x', 'end_y')]
        if proposal.get('action') == 'hover':
            coords = coords[:2] + coords[:2]
        if any((type(v) is not int for v in coords)):
            return {**base, 'status': 'unresolved', 'reason': 'scroll needs integer start and end coordinates'}
        with Image.open(frames[0]) as frame:
            (width, height) = frame.size
        (x, y, ex, ey) = coords
        if not (0 <= x < width and 0 <= y < height and (0 <= ex < width and 0 <= ey < height)) or ((x, y) == (ex, ey) and proposal.get('action') != 'hover'):
            return {**base, 'status': 'unresolved', 'reason': 'pointer coordinates outside screenshot or no displacement'}
    if proposal.get('action') == 'input_text' and (not (request.get('allow_input') or request.get('navigation_advice')) or not isinstance(proposal.get('text'), str)):
        return {**base, 'status': 'unresolved', 'reason': 'input is outside the routed task'}
    if proposal.get('action') not in ('tap', 'click', 'double_click', 'long_press', 'right_click', 'input_text', 'hover', 'drag'):
        return {**base, 'status': 'unresolved', 'reason': 'unsupported operation'}
    (x, y) = (proposal.get('x'), proposal.get('y'))
    if any((isinstance(v, bool) or not isinstance(v, (int, float)) for v in (x, y))):
        return {**base, 'status': 'unresolved', 'reason': 'missing position'}
    from pathlib import Path
    from PIL import Image
    frames = request.get('image_refs', [])
    if len(frames) != 1 or not Path(frames[0]).is_file():
        return {**base, 'status': 'unresolved', 'reason': 'current screenshot is missing'}
    with Image.open(frames[0]) as frame:
        (width, height) = frame.size
    if not (0 <= x < width and 0 <= y < height):
        return {**base, 'status': 'unresolved', 'reason': 'coordinates outside screenshot'}
    return {**base, 'status': 'matched', 'model_grounded': True,
            'basis': 'explicit registered object ref; ownership from records; coordinates supplied by model'}

def candidate_matches(request, target):
    """Select disclosed metadata for repair context, never an execution binding."""
    if not isinstance(target, str):
        return []
    target = target.strip()
    rows = candidate_rows(request)
    hits = [row['candidate'] for row in rows if target == row['target']]
    if len(hits) > 1:
        source = request.get('source', {})
        for rid in (source.get('working_region'), source.get('region')):
            local = [c for c in hits if c.get('region_ref', source.get('region')) == rid]
            if len(local) == 1:
                return local
    return hits

def candidate_key(request, candidate):
    return candidate['id']

def candidate_rows(request):
    return [{'target': candidate_key(request, c), 'name': c['name'], 'region': c.get('region_name', c.get('region_ref', request['source']['region'])), 'candidate': c} for c in request.get('backend_candidates', [])]

def candidate_line(row):
    import json
    return '- target=' + json.dumps(row['target'], ensure_ascii=False) + '；名称：' + row['name']

def disclose_candidates(request):
    """Display selected historical/visual guidance; this is not the ref registry."""
    from regrow.prompts.target_observation import render
    return render(request)
