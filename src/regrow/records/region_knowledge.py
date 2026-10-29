"""Stable numbered Region knowledge, updated without rewriting untouched paragraphs."""
from copy import deepcopy
import re

def normalize(region, records):
    """Read preserved old summaries once; never rewrite their original snapshot."""
    current = region.get('local_knowledge')
    if not current:
        return
    if all((re.fullmatch('k[0-9]+', key) and isinstance(value, str) for (key, value) in current.items())):
        for key in current:
            records.observe_id('knowledge', key)
        return
    parts = [current.get('summary', '')]
    parts += [row['description'] for row in current.get('conditions', []) if row.get('description')]
    region['local_knowledge'] = {records.allocate('knowledge'): text for text in parts if text.strip()}
    if current.get('parameters'):
        region['constraints'] = deepcopy(current['parameters'])

def validate(region, changes):
    current = region.get('local_knowledge', {})
    updated = [row['id'] for row in changes.get('update', [])]
    deleted = changes.get('delete', [])
    ids = updated + deleted
    if len(ids) != len(set(ids)):
        raise ValueError('同一知识段落只能修改或删除一次')
    if any((ref not in current for ref in ids)):
        raise ValueError('知识修改或删除必须引用已提供的段落编号')
    if any((not row['text'].strip() for row in changes.get('update', []))) or any((not text.strip() for text in changes.get('add', []))):
        raise ValueError('新增或修改的知识段落不能为空')

def apply(region, changes, records):
    validate(region, changes)
    result = deepcopy(region.get('local_knowledge', {}))
    for row in changes.get('update', []):
        result[row['id']] = row['text'].strip()
    for ref in changes.get('delete', []):
        del result[ref]
    for text in changes.get('add', []):
        result[records.allocate('knowledge')] = text.strip()
    region['local_knowledge'] = result
    return result

def text(region):
    return '\n'.join(region.get('local_knowledge', {}).values())
