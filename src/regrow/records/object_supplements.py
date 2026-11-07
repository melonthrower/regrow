"""Combine explicit same-object supplements before resolving reply relationships.

Only the derived reply is combined. Conflicts point to both original fields;
the model's answer and the persistent object identities remain unchanged.
"""
from copy import deepcopy
import json

from regrow.records.diagnostics import Rejected


def _same(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, ensure_ascii=False)


def _pointer(parts):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def _identity(row, kind, names):
    if not isinstance(row, dict):
        return None
    if kind == 'knowledge':
        if type(row.get('index')) is int:
            return ('index', row['index'])
        if 'index' not in row and isinstance(row.get('description'), str):
            return ('description', row['description'])
    elif kind == 'paragraph':
        if isinstance(row.get('id'), str):
            return ('id', row['id'])
    else:
        for field in ('ref', 'name'):
            if isinstance(row.get(field), str) and row[field]:
                if kind == 'control' and field == 'ref' and row[field] in names:
                    from regrow.records.object_knowledge import control_only
                    return ('ref', row[field], 'knowledge' if control_only(row) else 'observation')
                return ('ref' if field == 'ref' and row[field] in names else 'name', row[field])
    return None


class _Supplements:
    def __init__(self, names):
        self.names = names
        self.sources = {}
        self.errors = []

    def label(self, row):
        ref = row.get('ref')
        if isinstance(ref, str):
            return self.names.get(ref, ref)
        return row.get('name') if isinstance(row.get('name'), str) else None

    def remember(self, value, destination, source):
        self.sources[destination] = source
        children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        for key, child in children:
            self.remember(child, (*destination, key), (*source, key))

    def conflict(self, subject, field, before, after, destination, source):
        previous = self.sources[destination]
        self.errors.append({
            'code': 'object_supplement_conflict', 'object': subject,
            'path': _pointer(source), 'related_paths': [_pointer(previous)],
            'field': field, 'actual': [deepcopy(before), deepcopy(after)],
            'expected': '同一对象的同一字段在本批补充中须使用一致的值',
            'reason': '两条补充对这个字段给出了不同内容。',
            'repair': '核对两处内容，只修正冲突字段，保留其他补充。'})

    def rows(self, target, incoming, kind, destination, source, subject=''):
        positions = {_identity(row, kind, self.names): i for i, row in enumerate(target)
                     if _identity(row, kind, self.names) is not None}
        for i, row in enumerate(incoming):
            identity = _identity(row, kind, self.names)
            position = positions.get(identity) if identity is not None else None
            if position is None:
                position = len(target)
                target.append({} if isinstance(row, dict) else deepcopy(row))
                self.remember(target[position], (*destination, position), (*source, i))
                if identity is not None:
                    positions[identity] = position
            if not isinstance(row, dict):
                continue  # Preserve unreadable rows for the existing schema checks.
            label = self.label(row)
            owner = label or subject
            if kind == 'control' and subject and label:
                owner = subject + ' → ' + label
            self.fields(target[position], row, kind, (*destination, position), (*source, i), owner)

    def append(self, target, incoming, destination, source):
        for i, row in enumerate(incoming):
            if not any(_same(row, old) for old in target):
                position = len(target)
                target.append(deepcopy(row))
                self.remember(row, (*destination, position), (*source, i))

    def fields(self, target, incoming, kind, destination, source, subject):
        for field, value in incoming.items():
            dest, origin = (*destination, field), (*source, field)
            list_kind = ('control' if kind == 'region' and field == 'controls' else
                         'knowledge' if kind == 'control' and field == 'knowledge' else
                         'paragraph' if kind == 'local_knowledge' and field == 'update' else None)
            append = ((kind == 'local_knowledge' and field in ('add', 'delete'))
                      or field in ('remove_fields', 'image_conditions'))
            if isinstance(value, list) and (list_kind or append):
                if field not in target:
                    target[field] = []
                    self.remember([], dest, origin)
                if isinstance(target[field], list):
                    if list_kind:
                        self.rows(target[field], value, list_kind, dest, origin, subject)
                    else:
                        self.append(target[field], value, dest, origin)
                    continue
            if isinstance(value, dict):
                if field not in target:
                    target[field] = {}
                    self.remember({}, dest, origin)
                if isinstance(target[field], dict):
                    child_kind = 'local_knowledge' if kind == 'region' and field == 'local_knowledge' else 'fields'
                    self.fields(target[field], value, child_kind, dest, origin, subject)
                    continue
            if field not in target:
                target[field] = deepcopy(value)
                self.remember(value, dest, origin)
            elif not _same(target[field], value):
                self.conflict(subject, field, target[field], value, dest, origin)

    def consistency(self, row, kind, destination):
        if not isinstance(row, dict):
            return
        subject = self.label(row) or '本次对象'
        for field in row.get('remove_fields', []) if isinstance(row.get('remove_fields'), list) else []:
            if isinstance(field, str) and field in row:
                self.conflict(subject, field, row[field], '撤掉此字段', (*destination, field),
                              self.sources[(*destination, 'remove_fields')])
        if row.get('remove') is True:
            for field in set(row) - {'ref', 'name', 'candidate_index', 'remove', 'reason'}:
                self.conflict(subject, field, row[field], '撤回此对象', (*destination, field),
                              self.sources[(*destination, 'remove')])
        knowledge = row.get('local_knowledge')
        if kind == 'region' and isinstance(knowledge, dict):
            deleted = knowledge.get('delete', [])
            updates = knowledge.get('update', [])
            for i, update in enumerate(updates if isinstance(updates, list) else []):
                if isinstance(deleted, list) and isinstance(update, dict) and update.get('id') in deleted:
                    j = deleted.index(update['id'])
                    self.conflict(subject, '区块知识', update, '删除同一知识段落',
                                  (*destination, 'local_knowledge', 'update', i),
                                  self.sources[(*destination, 'local_knowledge', 'delete', j)])
        if kind == 'region' and isinstance(row.get('controls'), list):
            for i, control in enumerate(row['controls']):
                self.consistency(control, 'control', (*destination, 'controls', i))

    def shared_controls(self, reply):
        """Pure knowledge edits do not claim a current appearance or owner."""
        from regrow.records.object_knowledge import control_only
        patches = {}
        regions = reply.get('regions', [])
        for i, region in enumerate(regions if isinstance(regions, list) else []):
            if not isinstance(region, dict) or not isinstance(region.get('controls'), list):
                continue
            for j, control in enumerate(region['controls']):
                if not isinstance(control, dict) or not control_only(control):
                    continue
                ref = control.get('ref')
                if not isinstance(ref, str) or ref not in self.names:
                    continue
                patch = patches.setdefault(ref, {})
                self.fields(patch, control, 'control', ('shared_controls', ref),
                            ('regions', i, 'controls', j), self.names[ref])
        for ref, patch in patches.items():
            self.consistency(patch, 'control', ('shared_controls', ref))
        return patches

    def distribute_shared(self, result, patches):
        """Coalesce pure edits without moving facts out of current observations."""
        from regrow.records.object_knowledge import control_only
        locations = {}
        regions = result.get('regions', [])
        for i, region in enumerate(regions if isinstance(regions, list) else []):
            if not isinstance(region, dict) or not isinstance(region.get('controls'), list):
                continue
            for j, control in enumerate(region['controls']):
                if isinstance(control, dict) and control_only(control) and isinstance(control.get('ref'), str):
                    locations.setdefault(control['ref'], []).append((i, j, control))
        omitted = set()
        for ref, rows in locations.items():
            if ref not in patches:
                continue
            primary = rows[0]
            for i, j, control in rows:
                if control is primary[2]:
                    control.update({k: deepcopy(v) for k, v in patches[ref].items()
                                    if k == 'knowledge'})
                else:
                    # Keep this container readable until decode classifies its
                    # visibility, then omit its redundant pure knowledge row.
                    omitted.add(('regions', i, 'controls', j))
        return omitted

    def reject_conflicts(self):
        if self.errors:
            raise Rejected({'errors': self.errors, 'unchecked': [
                '其他补充仍保留在原回复中；冲突修正后继续正常校验和登记。']})


def combine(reply, names):
    """Coalesce Region/Control patches by their already decoded explicit identity."""
    result = deepcopy(reply)
    merger = _Supplements(names)
    shared = merger.shared_controls(reply)
    merger.reject_conflicts()
    for group, kind in (('regions', 'region'), ('controls', 'control')):
        if not isinstance(result.get(group), list):
            continue
        result[group] = []
        merger.rows(result[group], reply[group], kind, (group,), (group,))
        for i, row in enumerate(result[group]):
            merger.consistency(row, kind, (group, i))
    merger.reject_conflicts()
    return result, merger.distribute_shared(result, shared)


def accepted_knowledge(controls, names):
    """Merge knowledge only after observation/identity acceptance, before writes."""
    merger = _Supplements(names)
    updates = {}
    for i, control in enumerate(controls):
        ref = control.get('_matched_id') or control.get('ref')
        if ref not in names or 'knowledge' not in control:
            continue
        merger.fields(updates.setdefault(ref, {}), {'knowledge': control['knowledge']},
                      'control', ('accepted_controls', ref), ('controls', i), names[ref])
    merger.reject_conflicts()
    return {ref: patch['knowledge'] for ref, patch in updates.items()}
