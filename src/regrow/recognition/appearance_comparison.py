"""Label the first recorded appearance when an update proposes a second one."""
from copy import deepcopy
from pathlib import Path
import json
import jsonschema
from regrow.records.snapshots import load
from regrow.records.object_store import control_record
from regrow.recognition.identity_templates import variants
from regrow.prompts.frame_context import primary, label


def batches(run, original, candidate):
    snapshot, records, _ = load(run)
    ids = original.get('control_indexes', [])
    groups = {}
    for position, row in enumerate(candidate.get('controls', [])):
        index = row.get('index')
        if not row.get('add_image') or type(index) is not int or not 0 <= index < len(ids):
            continue
        control = control_record(records, ids[index])
        appearances = variants(control) if control is not None else []
        if len(appearances) != 1 or appearances[0].get('image_conditions'):
            continue
        old = appearances[0]
        if not old.get('source_image') or not old.get('bbox'):
            raise ValueError(control['name'] + '的旧外观缺少原图或范围，不能比较并补状态说明')
        source = str((snapshot / old['source_image']).resolve())
        groups.setdefault(source, []).append({
            'index': index, 'position': position, 'control': ids[index],
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
                '比较对象': [{'index': row['index'], '名称': row['name'],
                          '历史图中范围': ', '.join(str(row['historical_box'][key]) for key in ('left', 'top', 'right', 'bottom')),
                          '历史外观': row['description'],
                          '本次提议状态': row['proposed_state']} for row in rows]}
    fields = {'index': {'type': 'integer', 'enum': [r['index'] for r in rows]},
              'relation': {'type': 'string', 'enum': ['same_appearance', 'new_appearance', 'different_control', 'uncertain']},
              'historical_state': {'type': 'string'}, 'current_state': {'type': 'string'},
              'reason': {'type': 'string', 'minLength': 1}}
    q = {'role': 'appearance_comparison', 'stage': 'appearance_comparison',
         'system_prompt': text, 'fixed_parts': [{'path': '任务/控件外观状态比较.prompt', 'text': text}],
         'user_prompt': json.dumps(material, ensure_ascii=False),
         'screenshots': [str((Path(run) / primary(original)).resolve()), source],
         'source': deepcopy(original.get('source', {})),
         'control_indexes': deepcopy(original.get('control_indexes', [])),
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
    jsonschema.validate(reply, q['response_schema'])
    expected = {row['index']: row['name'] for row in q['appearance_rows']}
    if sorted(row['index'] for row in reply['comparisons']) != sorted(expected):
        raise ValueError('每个给定控件都需要且只需要一项外观比较')
    for row in reply['comparisons']:
        name = expected[row['index']]
        if row['relation'] in ('different_control', 'uncertain'):
            continue  # A valid negative judgment belongs to the parent proposal.
        if not row['historical_state'].strip() or not row['current_state'].strip():
            raise ValueError(name + '需要分别说明历史图和当前图的可见状态')
        if row['relation'] == 'new_appearance' and row['historical_state'].strip() == row['current_state'].strip():
            raise ValueError(name + '判断外观不同时，两条状态说明须能区分具体差异')
    return reply
