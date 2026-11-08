"""Read the Region partition explicitly accepted on this same frame."""
from pathlib import Path

def build(records, focus, frame, scope):
    bounds = (scope or {}).get('region_bounds', {})
    refs = (scope or {}).get('regions', list(bounds))
    if focus not in refs:
        return None
    return {'focus': focus, 'frame': str(Path(frame).resolve()),
            'source_call': (scope or {}).get('source_call'),
            'regions': [{'region': rid, 'name': records[rid]['name'],
                         'description': records[rid].get('description', ''),
                         'bounds': bounds.get(rid)} for rid in refs if rid in records]}

def prompt(context, completion=False):
    focus = next(r for r in context['regions'] if r['region'] == context['focus'])
    return {'本区块': focus['name'], '划分来源调用': context.get('source_call'),
            '其他已确认区块': [{'名称': r['name'], '职责': r['description']} for r in context['regions'] if r['region'] != context['focus']]}
