"""Complete one batch of new object appearances before publishing an update.

The semantic reply remains immutable. Geometry comes only from the original
after-image; the derived submission records both calls and uses normal commit.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import jsonschema
from regrow.records.snapshots import read, write_json
from regrow.prompts.frame_context import primary, label, select
from regrow.recognition.identity_templates import appearance_box

GEOMETRY = {'bbox', 'appearance_bbox', 'icon_bbox', 'click_bbox', 'click_area', 'x', 'y', 'end_x', 'end_y',
            'left', 'top', 'right', 'bottom'}
BOX = {'type': 'object', 'properties': {k: {'type': 'integer', 'minimum': 0}
       for k in ('left', 'top', 'right', 'bottom')},
       'required': ['left', 'top', 'right', 'bottom'], 'additionalProperties': False}
OPTIONAL_BOX = {'anyOf': [deepcopy(BOX), {'type': 'null'}]}


def semantic_schema(schema):
    from regrow.runtime.model_transport import expand_schema
    def strip(value):
        if isinstance(value, list):
            return [strip(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {k: deepcopy(v) if k == 'next_action' else strip(v) for k, v in value.items()}
        if 'properties' in result:
            result['properties'] = {k: v for k, v in result['properties'].items() if k not in GEOMETRY}
        if 'required' in result:
            result['required'] = [k for k in result['required'] if k not in GEOMETRY]
        return result
    return strip(expand_schema(schema))


def missing(candidate):
    from regrow.recognition.update_visibility import selected_indices
    current = selected_indices(candidate)
    rows = []
    for kind in ('regions', 'controls'):
        for i, row in enumerate(candidate.get(kind, [])):
            if kind == 'regions' and i not in current:
                continue
            known = row.get('ref') or (kind == 'controls' and 'index' in row)
            if (kind == 'controls' and appearance_box(row) is None
                    and any(field in row for field in ('appearance_bbox', 'bbox'))):
                continue
            if (known and not (kind == 'controls' and row.get('add_image'))) or (appearance_box(row) if kind == 'controls' else row.get('bbox')):
                continue
            rows.append({'path': f'/{kind}/{i}', **deepcopy(row)})
    return rows


def required_paths(original, candidate):
    """The executed source, observed destinations and their explicit owners."""
    source = original.get('source', {})
    required = set()
    for kind, actual in (('regions', source.get('region')), ('controls', source.get('control_ref'))):
        for i, row in enumerate(candidate.get(kind, [])):
            if actual and row.get('ref') == actual:
                required.add(f'/{kind}/{i}')
    for route in candidate.get('jump_to', []):
        from regrow.records.destination_refs import declared_paths
        required.update(declared_paths(route, candidate.get('regions', []), candidate.get('controls', [])))
    pending = list(required)
    while pending:
        path = pending.pop()
        _, kind, i = path.split('/')
        row = candidate[kind][int(i)]
        parent = row.get('region_index' if kind == 'controls' else 'parent_index')
        if type(parent) is int and 0 <= parent < len(candidate.get('regions', [])):
            path = f'/regions/{parent}'
            if path not in required:
                required.add(path)
                pending.append(path)
    return required


def request(root, original, candidate, rows, *, grounding=None):
    text = (Path(root) / 'regrow/prompts/任务/对象识别资料.prompt').read_text()
    rows = deepcopy(rows)
    grounding = grounding or {}
    for row in rows:
        if row['path'] in grounding:
            info = grounding[row['path']]
            row['名称'] = info['name']
            row['当前外观'] = info['state']
    paths = [row['path'] for row in rows]
    item = {'type': 'object', 'properties': {
        'path': {'type': 'string', 'enum': paths}, 'appearance_bbox': deepcopy(OPTIONAL_BOX), 'reason': {'type':'string'}},
        'required': ['path', 'appearance_bbox'], 'additionalProperties': False}
    q = {'role': 'object_registration', 'stage': 'object_registration',
         'system_prompt': text, 'fixed_parts': [{'path': '任务/对象识别资料.prompt', 'text': text}],
         'user_prompt': json.dumps({'待补齐对象': rows, '所属区块': candidate.get('regions', [])}, ensure_ascii=False),
         'screenshots': [primary(original)], 'source': deepcopy(original.get('source', {})),
         'response_schema': {'type': 'object', 'properties': {'objects': {
             'type': 'array', 'items': item, 'minItems': len(rows), 'maxItems': len(rows)}},
             'required': ['objects'], 'additionalProperties': False},
         'registration_paths': paths,
         'registration_required_paths': sorted(required_paths(original, candidate).intersection(paths))}
    if grounding:
        material = json.loads(q['user_prompt'])
        material['定位要求'] = '给定旧控件已完成历史身份与状态比较。现在逐一确认当前图中的具体对象，并框出符合其名称和当前外观的控件；确需消歧时用reason说明辨认依据；无法确认时appearance_bbox填null并说明缺口。'
        q['user_prompt'] = json.dumps(material, ensure_ascii=False)
        q['appearance_grounding'] = deepcopy(grounding)
    label(q, primary(original), '原动作后图；仅补齐本批对象外观，不判断动作效果')
    return q


def box_field(request, kind='objects'):
    """A retained supplement keeps the field in its actual saved contract."""
    from regrow.runtime.model_transport import expand_schema
    item = expand_schema(request['response_schema'])['properties'][kind]['items']
    fields = item['properties']
    return 'bbox' if kind == 'regions' or 'bbox' in fields and 'appearance_bbox' not in fields else 'appearance_bbox'


def validate(q, reply, run):
    from PIL import Image
    from regrow.records.registration_diagnostics import reply_errors, object_schema_error, Rejected
    errors = reply_errors(q, reply)
    fatal = [e for e in errors if not object_schema_error(q, reply, e)]
    if fatal:
        raise Rejected({'errors': fatal, 'unchecked': []})
    with Image.open(Path(run) / primary(q)) as im:
        width, height = im.size
    result = []
    without_appearance = set()
    field = box_field(q)
    for path in q['registration_paths']:
        matches = [(i, row) for i, row in enumerate(reply['objects']) if row.get('path') == path]
        reason = ''
        if len(matches) != 1:
            reason = '本次未返回该对象' if not matches else '同一对象返回了多项，尚不能确定采用哪一项'
        else:
            i, row = matches[0]
            prefix = f'/objects/{i}'
            details = [e['expected'] for e in errors if e['path'] == prefix or e['path'].startswith(prefix + '/')]
            if details:
                reason = '；'.join(details)
        if reason:
            result.append({'path': path, field: None, 'reason': reason})
            continue
        row = deepcopy(matches[0][1])
        b = row[field]
        if b is None:
            if path.startswith('/controls/'):
                without_appearance.add(path)
            if not row.get('reason', '').strip():
                row['reason'] = '本次未定位该对象，也未给出辨认依据'
        elif not (0 <= b['left'] < b['right'] <= width and 0 <= b['top'] < b['bottom'] <= height):
            row.update({field: None, 'reason': '识别范围超出本张图片或没有正面积'})
        result.append(row)
    blocked = [row for row in result if row[field] is None
               and row['path'] not in without_appearance
               and row['path'] in q.get('registration_required_paths', [])]
    if blocked:
        raise ValueError('本步必需对象尚未定位：' + '；'.join(row['path'] + '：' + row['reason'] for row in blocked))
    return {'objects': result, 'without_appearance': sorted(without_appearance)}


def retain_located(original, candidate, failed):
    """Keep independent observations; never drop the action object or its route."""
    if not failed:
        return candidate, [], {}
    from regrow.recognition.discovery_completion import partition
    rejected = {'regions': set(), 'controls': set()}
    for path in failed:
        _, kind, position = path.split('/')
        rejected[kind].add(int(position))
    accepted, gaps = partition(candidate, rejected['regions'], rejected['controls'])
    omitted = {'regions': {g['index'] for g in gaps if g['kind'] == 'region'},
               'controls': {g['index'] for g in gaps if g['kind'] == 'control'}}
    source = original.get('source', {})
    for gap in gaps:
        row = gap['proposal']
        path = '/' + ('regions' if gap['kind'] == 'region' else 'controls') + '/' + str(gap['index'])
        gap['reason'] = failed.get(path, '所属区块尚未确认，保留该对象待后续观察。')
        actual = source.get('control_ref') if gap['kind'] == 'control' else source.get('region')
        if row.get('ref') and row['ref'] == actual:
            raise ValueError('本次实际操作对象「' + gap['name'] + '」仍需核对：' + gap['reason'])
    indexes = {kind: [i for i in range(len(candidate.get(kind, []))) if i not in omitted[kind]]
               for kind in ('regions', 'controls')}
    maps = {kind: {old: new for new, old in enumerate(values)} for kind, values in indexes.items()}
    if 'current_regions' in candidate:
        names = original.get('region_names') or original.get('discovery_context', {}).get('region_names', {})
        def identity(row):
            ref = row.get('_matched_id') or row.get('ref')
            return names.get(ref, ref) if isinstance(ref, str) else None
        withheld = {identity(candidate['regions'][i]) for i in omitted['regions']} - {None, ''}
        accepted['current_regions'] = []
        indexes['current_regions'] = []
        for i, member in enumerate(candidate['current_regions']):
            if 'region_index' in member:
                old = member['region_index']
                if old in omitted['regions']:
                    continue
                member = {**member, 'region_index': maps['regions'].get(old, old)}
            elif identity(member) in withheld:
                continue
            accepted['current_regions'].append(deepcopy(member))
            indexes['current_regions'].append(i)
    from regrow.records.destination_refs import declared_paths
    withheld_paths = {f'/{kind}/{i}' for kind, values in omitted.items() for i in values}
    for position, route in enumerate(candidate.get('jump_to', [])):
        pending_targets = declared_paths(route, candidate.get('regions', []), candidate.get('controls', [])) & withheld_paths
        if pending_targets and 'region' in route:
            from regrow.records.diagnostics import reject
            reject('destination_target_pending', route.get('control') or route['region'],
                   {'访问目标': deepcopy(route), '尚未接收的目标观察': sorted(pending_targets)},
                   '本次目标观察或新对象先通过接收；已有对象不要求重复登记',
                   path=f'/jump_to/{position}', field='访问目标',
                   reason='本次访问目标对应的观察或新对象仍有错误，保留关系等待修正。')
    for route in accepted.get('jump_to', []):
        for field, kind in (('region_index', 'regions'), ('control_index', 'controls')):
            if field not in route:
                continue
            old = route[field]
            if old not in maps[kind]:
                row = candidate[kind][old] if type(old) is int and 0 <= old < len(candidate.get(kind, [])) else {}
                name = next((row[k] for k in ('name', 'ref') if isinstance(row.get(k), str) and row[k]), '目标对象')
                raise ValueError('本次实际访问关系的目标「' + name + '」尚未定位或引用无效，不能撤掉访问关系来完成登记。')
            route[field] = maps[kind][old]
    return accepted, gaps, indexes


def remap_gaps(gaps, previous):
    """Keep retained diagnostics attached to their original reply row."""
    for gap in gaps:
        kind = 'regions' if gap['kind'] == 'region' else 'controls'
        path = f'/{kind}/{gap["index"]}'
        for error in gap.get('errors', []):
            error['path'] = f'/{kind}/{previous[kind][gap["index"]]}' + error['path'][len(path):]
        gap['index'] = previous[kind][gap['index']]
        field = 'parent_index' if kind == 'regions' else 'region_index'
        i = gap['proposal'].get(field)
        if type(i) is int and 0 <= i < len(previous['regions']):
            gap['proposal'][field] = previous['regions'][i]


def partition_request(original, candidate, failed, errors=()):
    """Reuse object gaps and original-index mappings across acceptance stages."""
    try:
        accepted, gaps, indexes = retain_located(original, candidate, failed)
    except ValueError as dependency:
        # A dependency failure must not erase the validator facts that caused
        # this partition. Keep both in their actual order for ordinary repair.
        from regrow.records.diagnostics import diagnostic, Rejected
        primary = deepcopy(list(errors))
        if not primary:
            for path, reason in failed.items():
                _, kind, position = path.split('/')
                row = candidate[kind][int(position)]
                primary.append({'code': 'object_registration', 'path': path,
                    'object': row.get('name') or row.get('ref') or '本次登记对象',
                    'actual': deepcopy(row), 'expected': reason, 'reason': reason})
        dependent = diagnostic(dependency)
        if isinstance(dependent, dict):
            primary.extend(deepcopy(dependent.get('errors', [])))
        else:
            primary.append({'code': 'registration_dependency', 'object': '本次登记的依赖对象',
                            'actual': str(dependency), 'expected': '依赖对象通过接收后才能登记关联内容'})
        raise Rejected({'errors': primary, 'unchecked': []}) from dependency
    if not gaps:
        return original, accepted
    q = deepcopy(original)
    previous = {kind: q.get('registration_source_indices', {}).get(kind, list(range(len(candidate.get(kind, [])))))
                for kind in indexes}
    for gap in gaps:
        kind = 'regions' if gap['kind'] == 'region' else 'controls'
        path = f'/{kind}/{gap["index"]}'
        gap['errors'] = [deepcopy(e) for e in errors if e.get('path') == path or e.get('path', '').startswith(path + '/')]
    remap_gaps(gaps, previous)
    q['registration_gaps'] = deepcopy(q.get('registration_gaps', [])) + gaps
    q['registration_source_indices'] = {kind: [previous[kind][i] for i in indexes[kind]] for kind in indexes}
    return q, accepted


def isolate_schema(request, candidate):
    """Only readable independent observation rows may be withheld before decoding."""
    from regrow.records.registration_diagnostics import reply_errors, object_schema_error, Rejected
    from regrow.records.task_assessments import row_error
    errors = reply_errors(request, candidate)
    if not errors:
        return request, candidate
    if any(not object_schema_error(request, candidate, e) for e in errors):
        raise Rejected({'errors': errors, 'unchecked': []})
    failed = {}
    for error in errors:
        if row_error(request, candidate, error):
            continue
        path = '/' + '/'.join(error['path'].strip('/').split('/')[:2])
        failed[path] = error['expected']
    if not failed:
        return request, candidate
    q, accepted = partition_request(request, candidate, failed, errors)
    remaining = [error for error in reply_errors(q, accepted) if not row_error(q, accepted, error)]
    if remaining:
        raise Rejected({'errors': remaining, 'unchecked': []})
    return q, accepted


def isolate_update(run, request, candidate, binding=None):
    """Check observation rows before supplement calls; keep the real result intact."""
    from regrow.recognition.region_identity import prepare
    from regrow.records.registration_diagnostics import collect, Rejected
    from regrow.records.snapshots import load
    _, records, _ = load(run)
    q, accepted = isolate_schema(request, candidate)
    while True:
        resolved_q, resolved, _ = prepare(run, q, accepted)
        report = collect('update', resolved_q, resolved, records, binding, frame=Path(run) / primary(q))
        if not report['errors']:
            return q, accepted
        failed = {}
        for error in report['errors']:
            parts = error.get('path', '').strip('/').split('/')
            if (len(parts) < 2 or parts[0] not in ('regions', 'controls') or not parts[1].isdigit()
                    or not 0 <= int(parts[1]) < len(accepted.get(parts[0], []))):
                earlier = [deepcopy(item) for gap in q.get('registration_gaps', [])
                           for item in gap.get('errors', [])]
                raise Rejected({**report, 'errors': earlier + report['errors']})
            failed['/' + '/'.join(parts[:2])] = error.get('repair') or error.get('expected', '对象尚未确认')
        q, accepted = partition_request(q, accepted, failed, report['errors'])
        # Each pass removes at least one reported row and its dependent rows.


def save_candidate(runner, job, q, candidate):
    for gap in q.get('registration_gaps', []):
        gap.setdefault('source_call', job['call'])
        gap.setdefault('source_frame', primary(q))
    job.update(request=q, candidate=candidate)
    runner.save(job)
    folder = runner.run / 'calls' / job['call']
    write_json(folder / 'registration_request.json', q)
    write_json(folder / 'registration_candidate.json', candidate)


def revised_request(request, source_call):
    """A new corrected call owns its complete effective array, not old row offsets."""
    q = deepcopy(request)
    for gap in q.get('registration_gaps', []):
        gap.setdefault('source_call', source_call)
        gap.setdefault('source_frame', primary(q))
    q.pop('registration_source_indices', None)
    q.pop('registration_sources', None)
    return q


def reused_boxes(saved, current):
    """Reuse a complete verified batch only with unique unchanged object bindings."""
    old = saved.get('request', {})
    if not old or primary(old) != primary(current):
        return None
    def bindings(q):
        result = {}
        for path in q.get('registration_paths', []):
            info = q.get('appearance_grounding', {}).get(path)
            if not info or not info.get('control'):
                return None
            identity = (info['control'], info.get('state'), info.get('comparison_call'))
            if identity in result:
                return None
            result[identity] = path
        return result or None
    try:
        old_keys, new_keys = bindings(old), bindings(current)
    except (ValueError, TypeError):
        return None
    if not old_keys or not new_keys or set(old_keys) != set(new_keys):
        return None
    boxes = {r['path']: r for r in saved['candidate']['objects']}
    if set(boxes) != set(old_keys.values()) or any(not appearance_box(r) for r in boxes.values()):
        return None
    return [{'path': path, box_field(current): deepcopy(appearance_box(boxes[old_keys[key]])),
             **({'reason': boxes[old_keys[key]]['reason']} if boxes[old_keys[key]].get('reason') else {})}
            for key, path in new_keys.items()]


def complete(runner, job):
    """Resume a normal child repair; no GUI capture or partial graph publication."""
    if job['stage'] != 'update':
        return
    candidate = job.get('candidate') or {}
    binding = read(runner.run / 'action_attempts' / job['attempt'] / 'binding.json') if job.get('attempt') else None
    q, candidate = isolate_update(runner.run, job['request'], candidate, binding)
    if q != job['request'] or candidate != job['candidate']:
        save_candidate(runner, job, q, candidate)
    # A derived submission is already the active request. Do not rebuild it
    # from a historical semantic request or revive an old request cache.
    if job['request'].get('registration_sources') and not missing(candidate):
        job.pop('registration_submission', None)
        return
    digest = hashlib.sha256(json.dumps([candidate, job['request'].get('control_refs')],
                                      sort_keys=True).encode()).hexdigest()[:16]
    enriched = deepcopy(candidate)
    labels = []
    grounding = {}
    failed = {}
    from regrow.recognition import appearance_comparison
    from regrow.traversal.step_repair import pending
    for number, (source, batch) in enumerate(appearance_comparison.batches(runner.run, job['request'], candidate, failed=failed)):
        comparison = appearance_comparison.request(runner.root, runner.run, job['request'], source, batch)
        necessary = required_paths(job['request'], candidate)
        comparison['comparison_required_refs'] = [row['ref'] for row in batch if f'/controls/{row["position"]}' in necessary]
        key = appearance_comparison.comparison_key(comparison)
        pointer = str(Path(job['path']).parent / ('appearance-' + key + '.json'))
        cache = job.setdefault('appearance_comparisons', {})
        saved = cache.get(pointer)
        if saved is None:
            # Existing job results remain usable after upgrading the cache key.
            saved = next((value for value in cache.values()
                          if value.get('request', {}).get('appearance_rows')
                          and appearance_comparison.comparison_key(value['request']) == key), None)
        if saved is None:
            child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot,
                                 runner.available, pointer_name=pointer)
            q = None if pending(runner.run, pointer) else comparison
            saved = child.perform('appearance_comparison', q)
            cache[pointer] = saved
            runner.save(job)
        replies = appearance_comparison.replies_by_control(saved)
        for old in batch:
            reply = replies[old['control']]
            if reply['relation'] in ('different_control', 'uncertain'):
                failed['/controls/' + str(old['position'])] = old['name'] + '的外观比较未确认本次复用：' + reply['reason']
                continue
            current = enriched['controls'][old['position']]
            current['add_image'] = reply['relation'] == 'new_appearance'
            current['image_conditions'] = [reply['current_state']] if current['add_image'] else []
            labels.append({'control': old['control'], 'image': old['image'],
                           'state': reply['historical_state'], 'source_call': saved['call'],
                           'reason': reply['reason']})
            if current['add_image']:
                grounding['/controls/' + str(old['position'])] = {
                    'control': old['control'], 'name': old['name'],
                    'state': reply['current_state'], 'comparison_call': saved['call']}
    rows = [row for row in missing(enriched) if row['path'] not in failed]
    if not rows and not labels and not failed:
        return
    appearance_call = None
    if rows:
        pointer = str(Path(job['path']).parent / ('objects-' + digest + '.json'))
        saved = job.get('object_registration', {})
        current = request(runner.root, job['request'], enriched, rows, grounding=grounding)
        reused = reused_boxes(saved.get('result', {}), current)
        if reused is not None:
            result = deepcopy(saved['result'])
            result['candidate']['objects'] = reused
        elif saved.get('digest') == digest:
            result = saved['result']
        else:
            child = type(runner)(runner.root, runner.run, runner.call, runner.screenshot,
                                 runner.available, pointer_name=pointer)
            q = None if pending(runner.run, pointer) else current
            result = child.perform('object_registration', q)
            job['object_registration'] = {'digest': digest, 'result': result}
            runner.save(job)
        appearance_call = result['call']
        # Child acceptance may isolate malformed/missing rows. The original
        # model answer remains in candidate/response for correction and audit.
        located_request = current if reused is not None else result['request']
        located = validate(located_request, result['candidate'], runner.run)
        for row in located['objects']:
            _, kind, index = row['path'].split('/')
            if (row[box_field(located_request)] is None
                    and row['path'] not in located['without_appearance']):
                failed[row['path']] = row['reason']
            else:
                field = box_field(job['request'], kind)
                enriched[kind][int(index)][field] = row[box_field(located_request)]
    q, enriched = partition_request(job['request'], enriched, failed)
    q = deepcopy(q)
    gaps = q.get('registration_gaps', [])
    source_indices = q.get('registration_source_indices', {})
    from regrow.runtime.model_transport import expand_schema
    q['response_schema'] = expand_schema(q['response_schema'])
    for kind in ('regions', 'controls'):
        fields = q['response_schema']['properties'][kind]['items']['properties']
        fields[box_field(q, kind)] = deepcopy(OPTIONAL_BOX if kind == 'controls' else BOX)
    select(q, primary(job['request']), '原动作后图；识别范围由单图补登记取得')
    q['semantic_request'] = deepcopy(job['request'])
    q['semantic_request'].pop('control_identity_reviews', None)
    q['registration_sources'] = {'semantic_call': job['call'], 'appearance_call': appearance_call}
    if gaps:
        q['registration_gaps'] = gaps
        q['registration_source_indices'] = source_indices
    q['appearance_labels'] = labels
    folder = runner.run / 'calls' / job['call']
    job['registration_submission'] = {
        'objects': [{'path': '/' + kind + '/' + str(index), 'appearance_bbox': deepcopy(appearance_box(row))}
                    for kind in ('regions', 'controls')
                    for index, row in enumerate(enriched.get(kind, [])) if appearance_box(row)],
        'registration_sources': deepcopy(q['registration_sources']),
        'registration_gaps': deepcopy(gaps),
        'registration_source_indices': deepcopy(source_indices),
        'schema_extension': {'appearance_bbox': deepcopy(OPTIONAL_BOX), 'bbox': deepcopy(BOX)}}
    save_candidate(runner, job, q, enriched)


def semantic_revision(reviewed, candidate):
    original = deepcopy(reviewed.get('semantic_request', reviewed))
    original['control_refs'] = reviewed.get('control_refs', original.get('control_refs', []))
    original['control_identity_reviews'] = deepcopy(reviewed.get('control_identity_reviews', []))
    for key in ('registration_gaps', 'registration_source_indices'):
        if key in reviewed:
            original[key] = deepcopy(reviewed[key])
        else:
            original.pop(key, None)
    result = deepcopy(candidate)
    # Strip geometry only from observation rows, not named knowledge/parameters.
    if isinstance(result, dict):
        for kind in ('regions', 'controls'):
            for row in result.get(kind, []):
                if isinstance(row, dict):
                    for key in GEOMETRY:
                        row.pop(key, None)
    return original, result
