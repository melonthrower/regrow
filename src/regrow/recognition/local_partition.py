"""Same-frame partition context for local discovery and publication checks."""
from regrow.records.object_store import owned_controls
from pathlib import Path
import hashlib
from regrow.recognition import identity_templates as templates
KEYS = ('left', 'top', 'right', 'bottom')

def build(records, focus, frame, scope, ranking):
    bounds = (scope or {}).get('region_bounds', {})
    refs = (scope or {}).get('regions', list(bounds))
    if focus not in refs:
        return None
    rows = []
    for rid in refs:
        box = bounds.get(rid)
        if rid not in records:
            continue
        region = records[rid]
        controls = []
        for hit in ranking.get(rid, {}).get('anchors', []):
            cid = hit['control']
            control = owned_controls(region)[cid]
            observation = templates.latest(control) or {}
            source = {**observation.get('evidence', {}), **observation}
            controls.append({'control': cid, 'name': control['name'], 'box': hit['box'], 'score': hit.get('score'), 'template_source': {k: source[k] for k in ('source_call', 'observation', 'source_field') if k in source}})
        rows.append({'region': rid, 'name': region['name'], 'description': region.get('description', ''), 'bounds': box, 'controls': controls})
    path = Path(frame)
    return {'focus': focus, 'frame': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None, 'source_call': (scope or {}).get('source_call'), 'regions': rows}

def exit_guidance(completion=False):
    if completion:
        return '本轮是固定同图补全，不能直接改变已登记划分或交回重定位。focus仍在当前前景时保持原范围；需重新核对划分的缺口用completion_updates.unresolved保留，两索引可为null，regions/controls可留空并在uncertainties说明。实图证明某缺口属于别区或重复时可excluded并说明，不凭匹配候选排除。区块确已离开前景时如实说明；没有控件不等于离开前景。'
    return 'focus仍在当前前景时保持已确认范围，仅登记本区控件，纯展示区可以没有控件。需要核对划分写uncertainties；区块确已关闭或被另一表面接管时才报告not_interactive并留空。'

def prompt(context, completion=False):
    focus = next((r for r in context['regions'] if r['region'] == context['focus']))
    return {'本区块': focus['name'], '划分来源调用': context.get('source_call'), '其他已确认区块': [{'名称': r['name'], '职责': r['description'], '已匹配控件': [{'名称': c['name'], '当前候选位置': c['box'], '历史模板出处': c['template_source']} for c in r['controls']]} for r in context['regions'] if r['region'] != context['focus']], '用途': '同一截图已确认的区块划分；其他区块与控件只作归属和防重参照，不在本轮登记范围。匹配不是身份结论。局部候选缺席不证明控件是新对象。' + exit_guidance(completion)}

def errors(request, reply):
    context = request.get('discovery_context', {}).get('partition_context')
    if not context:
        return []
    focus = next((r for r in context['regions'] if r['region'] == context['focus']))
    result = []

    def add(code, path, obj, actual, expected):
        result.append({'code': code, 'path': path, 'object': obj, 'actual': actual, 'expected': expected, 'repair': '核对同帧已确认划分与已有控件归属；不要改身份图裁图来迁就归属。其他区控件不在本轮登记范围，不自动合并身份。' + exit_guidance(request.get('discovery_context', {}).get('completion', False))})
    for (i, control) in enumerate(reply.get('controls', [])):
        if control.get('identity') != 'new':
            continue
        identity = control.get('bbox')
        if not identity:
            continue
        for owner in context['regions']:
            if owner['region'] == context['focus']:
                continue
            for candidate in owner['controls']:
                (a, c, d, e) = candidate['box']
                overlap = max(0, min(d, identity['right']) - max(a, identity['left'])) * max(0, min(e, identity['bottom']) - max(c, identity['top']))
                area = min((d - a) * (e - c), (identity['right'] - identity['left']) * (identity['bottom'] - identity['top']))
                if area > 0 and overlap / area >= 0.5:
                    add('local_control_duplicate', f'/controls/{i}/identity', control.get('name', ''), {'submitted': identity, 'candidate_position': candidate['box']}, owner['name'] + ' → ' + candidate['name'] + '（视觉候选，需核对）')
    return result
