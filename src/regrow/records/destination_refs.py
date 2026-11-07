"""Resolve reported destinations to identities, independently of observation rows."""
from regrow.records.diagnostics import reject
from regrow.records.object_store import owned_controls, observation_history


def declared_paths(value, regions, controls):
    """Only declarations actually supplied by this reply can need more evidence."""
    from regrow.records.object_knowledge import control_only, region_only
    result = set()
    if 'region_index' in value:  # Saved positional contracts retain their meaning.
        for field, group, rows in (('region_index', 'regions', regions),
                                   ('control_index', 'controls', controls)):
            index = value.get(field)
            if type(index) is int and 0 <= index < len(rows):
                result.add(f'/{group}/{index}')
        return result
    target = value.get('region')
    owners = {i for i, row in enumerate(regions)
              if target in (row.get('ref'), row.get('name'))}
    for i in owners:
        if not region_only(regions[i]):
            result.add(f'/regions/{i}')
    control = value.get('control')
    if control is not None:
        for i, row in enumerate(controls):
            if control_only(row):
                continue
            if row.get('ref') == control or (row.get('name') == control and row.get('region_index') in owners):
                result.add(f'/controls/{i}')
    return result


def _owner_error(records, target, cid, position):
    from regrow.records.object_store import control_record
    name = (control_record(records, cid) or {}).get('name', cid)
    reject('destination_control_owner', name,
           {'目标区块': records[target]['name'], '目标控件': name,
            '控件已登记所属区块': [r['name'] for r in records.values() if cid in owned_controls(r)]},
           '到达控件属于所填写的目标区块', path=f'/jump_to/{position}/control',
           field='到达后的目标控件', reason='“' + name + '”不属于目标区块“' + records[target]['name'] + '”。',
           repair='核对目标区块；只确认到达区块时省略control。')


def resolve(value, records, region_refs, controls, call, position, *, regions=()):
    """Existing IDs use the object table; names identify this batch's new objects."""
    reference = value.get('region')
    if 'region_index' in value:
        index = value['region_index']
        target = region_refs[index] if type(index) is int and 0 <= index < len(region_refs) else None
        field = 'region_index'
        reference = index
    else:
        field = 'region'
        matches = [region_refs[i] for i, row in enumerate(regions)
                   if not row.get('ref') and row.get('name') == reference and i < len(region_refs)]
        target = reference if reference in records else matches[0] if len(matches) == 1 else None
    if target not in records:
        reject('destination_reference', reference or '本次访问目标', reference,
               '已提供的已有区块ID，或本批成功登记的新区块名称',
               path=f'/jump_to/{position}/{field}', field='访问目标区块',
               reason='访问目标没有对应的已登记区块；已有区块不需要重复提交登记行。')
    if 'control' not in value and 'control_index' not in value:
        return target, None
    reference = value.get('control')
    ci = value.get('control_index')
    if 'control_index' in value:
        row = controls[ci] if type(ci) is int and 0 <= ci < len(controls) else None
        reference = row.get('ref') or row.get('name') if row else ci
        candidates = [(ci, row)] if row else []
        from regrow.records.object_knowledge import control_only
        if row and not control_only(row):
            owner = row.get('region_index')
            if type(owner) is not int or not 0 <= owner < len(region_refs) or region_refs[owner] != target:
                reject('destination_control_owner', reference or records[target]['name'],
                       {'目标区块': records[target]['name'], '控件本次观察所属区块':
                        records[region_refs[owner]]['name'] if type(owner) is int and 0 <= owner < len(region_refs) else '未确认'},
                       '到达控件的本次观察属于所填写的目标区块',
                       path=f'/jump_to/{position}/control_index', field='到达后的目标控件',
                       reason='目标控件的本次观察不属于指定区块。')
    else:
        candidates = [(i, row) for i, row in enumerate(controls)
                      if not row.get('ref') and row.get('name') == reference]
    from regrow.records.object_store import control_record
    if reference and control_record(records, reference) is not None:
        if reference not in owned_controls(records[target]):
            _owner_error(records, target, reference, position)
        return target, reference
    matches = []
    for index, row in candidates:
        owner = row.get('region_index')
        if type(owner) is not int or not 0 <= owner < len(region_refs) or region_refs[owner] != target:
            continue
        matches.extend(cid for cid, control in owned_controls(records[target]).items()
                       if any(event.get('evidence', {}).get('source_call') == call and
                              event.get('evidence', {}).get('source_field') == f'/controls/{index}'
                              for event in observation_history(control)))
    if len(set(matches)) != 1:
        reject('destination_control_reference', reference or records[target]['name'],
               {'填写的目标控件': reference, '目标区块': records[target]['name'], '对应控件': matches},
               '该区块的已有控件ID，或本批在该区块成功登记的新控件名称',
               path=f'/jump_to/{position}/control', field='到达后的目标控件',
               reason='目标控件没有唯一登记结果，或不属于指定的目标区块。')
    return target, matches[0]
