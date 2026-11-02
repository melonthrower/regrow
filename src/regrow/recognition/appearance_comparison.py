"""Label the first recorded appearance when an update proposes a second one."""
from copy import deepcopy
from pathlib import Path
import json
import jsonschema
from regrow.records.snapshots import load
from regrow.records.object_store import control_record
from regrow.recognition.identity_templates import variants
from regrow.prompts.frame_context import primary, label


def batches(run, original, candidate, *, failed=None):
    snapshot, records, _ = load(run)
    groups = {}
    for position, row in enumerate(candidate.get('controls', [])):
        ref = row.get('ref')
        if not row.get('add_image') or not ref:
            continue
        control = control_record(records, ref)
        appearances = variants(control) if control is not None else []
        if len(appearances) != 1 or appearances[0].get('image_conditions'):
            continue
        old = appearances[0]
        if not old.get('source_image') or not old.get('bbox'):
            reason = control['name'] + '的旧外观缺少原图或范围，不能比较并补状态说明'
            if failed is None:
                raise ValueError(reason)
            failed['/controls/' + str(position)] = reason
            continue
        source = str((snapshot / old['source_image']).resolve())
        groups.setdefault(source, []).append({
            'ref': ref, 'position': position, 'control': ref,
            'name': control['name'], 'historical_box': old['bbox'],
            'image': str((snapshot / old['image']).resolve()),
            'description': old.get('description', ''),
            'proposed_state': row.get('image_conditions', [])})
    return list(groups.items())


def request(root, run, original, source, rows):
    from regrow.prompts.prompt_material import body
    text = (Path(root) / 'regrow/prompts/任务/控件外观状态比较.prompt').read_text()
    context = body(original)[0]
    keys = ('工作区块', '实际来源区块', '实际入口', '本轮探索任务', '任务目标')
    original_context = {k: context[k] for k in keys if k in context}
    original_context['实际操作'] = [
        {'动作': action['action'], **({'输入': action['text']} if action.get('text') else {})}
        for action in context.get('实际动作', [])]
    material = {'原步骤': original_context,
                '比较对象': [{'ref': row['ref'], '名称': row['name'],
                          '历史图中范围': ', '.join(str(row['historical_box'][key]) for key in ('left', 'top', 'right', 'bottom')),
                          '历史外观': row['description'],
                          '本次提议状态': row['proposed_state']} for row in rows]}
    fields = {'ref': {'type': 'string', 'enum': [r['ref'] for r in rows]},
              'relation': {'type': 'string', 'enum': ['same_appearance', 'new_appearance', 'different_control', 'uncertain']},
              'historical_state': {'type': 'string'}, 'current_state': {'type': 'string'},
              'reason': {'type': 'string', 'minLength': 1}}
    q = {'role': 'appearance_comparison', 'stage': 'appearance_comparison',
         'system_prompt': text, 'fixed_parts': [{'path': '任务/控件外观状态比较.prompt', 'text': text}],
         'user_prompt': json.dumps(material, ensure_ascii=False),
         'screenshots': [str((Path(run) / primary(original)).resolve()), source],
         'source': deepcopy(original.get('source', {})),
         'control_refs': deepcopy(original.get('control_refs', [])),
         'appearance_rows': deepcopy(rows),
         'response_schema': {'type': 'object', 'properties': {'comparisons': {
             'type': 'array', 'items': {'type': 'object', 'properties': fields,
             'required': list(fields), 'additionalProperties': False},
             'minItems': len(rows), 'maxItems': len(rows)}},
             'required': ['comparisons'], 'additionalProperties': False}}
    label(q, q['screenshots'][0], '原动作后图；核对当前外观')
    label(q, source, '已保存模板的历史原图；给定范围指认旧控件')
    return q


def validate(q, reply, run=None):
    from regrow.records.registration_diagnostics import reply_errors, object_schema_error, Rejected
    errors = reply_errors(q, reply)
    fatal = [e for e in errors if not object_schema_error(q, reply, e)]
    if fatal:
        raise Rejected({'errors': fatal, 'unchecked': []})
    expected = {row['ref']: row['name'] for row in q['appearance_rows']}
    result = []
    invalid = set()
    for ref, name in expected.items():
        matches = [(i, row) for i, row in enumerate(reply['comparisons']) if row.get('ref') == ref]
        reason = ''
        if len(matches) != 1:
            reason = '本次未返回该控件的比较' if not matches else '同一控件返回了多项比较，尚不能确定采用哪一项'
        else:
            i, row = matches[0]
            prefix = f'/comparisons/{i}'
            details = [e['expected'] for e in errors if e['path'] == prefix or e['path'].startswith(prefix + '/')]
            if details:
                reason = '；'.join(details)
            elif row['relation'] not in ('different_control', 'uncertain'):
                if not row['historical_state'].strip() or not row['current_state'].strip():
                    reason = name + '缺少历史或当前可见状态说明'
                elif row['relation'] == 'new_appearance' and row['historical_state'].strip() == row['current_state'].strip():
                    reason = name + '的两条状态说明未解释外观差异'
        if reason:
            invalid.add(ref)
            result.append({'ref': ref, 'relation': 'uncertain', 'historical_state': '',
                           'current_state': '', 'reason': reason})
        else:
            result.append(deepcopy(matches[0][1]))
    blocked = [row for row in result if row['ref'] in invalid
               and row['ref'] in q.get('comparison_required_refs', [])]
    if blocked:
        raise ValueError('本步必需对象的身份或外观尚未确认：' + '；'.join(expected[row['ref']] + '：' + row['reason'] for row in blocked))
    return {'comparisons': result}


def comparison_key(request):
    """One frozen visual question; wording of a proposed state is not evidence.

    Kept within the existing repair job. Stable control IDs decouple cached
    answers from output-array ordering.
    """
    import hashlib
    rows = [{k: row.get(k) for k in ('control', 'name', 'description', 'image', 'historical_box')}
            for row in request['appearance_rows']]
    rows.sort(key=lambda row: row['control'])
    evidence = {'images': [str(Path(p).resolve()) for p in request['screenshots']], 'controls': rows}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def replies_by_control(saved):
    ids = {row['ref']: row['control'] for row in saved['request']['appearance_rows']}
    accepted = validate(saved['request'], saved['candidate'])
    return {ids[row['ref']]: row for row in accepted['comparisons']}
