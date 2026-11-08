"""Resolve the reported foreground; retain old visibility rules for saved replies."""

def has_interactive(reply):
    """Retained name: test whether a foreground Region was observed, not controls."""
    if 'current_regions' in reply:
        return bool(reply['current_regions'])
    return bool(reply.get('regions') or any(p['state'] in ('retained_interactive', 'changed_interactive')
                                          for p in historical_changes(reply)))

def historical_changes(reply, records=None, names=None):
    """Read archived pre-current_regions replies; new replies never use this field."""
    if 'current_regions' in reply:
        return []
    from regrow.recognition.region_candidate_names import resolve
    return [{'region': resolve(records, row['ref'], names) if records is not None else row['ref'],
             'state': row['state'], **({'evidence': row['evidence']} if row.get('evidence') else {})}
            for row in reply.get('previous_regions', [])]

def selected_indices(reply, names=None):
    """Rows explicitly selected as current, including rows selected by stable ref."""
    if 'current_regions' not in reply:
        return set(range(len(reply.get('regions', []))))
    names = names or {}
    refs = {names.get(row['ref'], row['ref']) for row in reply['current_regions'] if row.get('ref')}
    indexes = {row['region_index'] for row in reply['current_regions'] if type(row.get('region_index')) is int}
    indexes.update(i for i, row in enumerate(reply.get('regions', []))
                   if row.get('name') in refs or row.get('ref')
                   and (row.get('_matched_id') or names.get(row['ref'], row['ref'])) in refs)
    return indexes

def current_refs(reply, records, delta_refs, names=None):
    """Preserve membership positions for evidence; callers may deduplicate IDs."""
    from regrow.recognition.region_candidate_names import resolve
    return [delta_refs[row['region_index']] if 'region_index' in row
            else resolve(records, row['ref'], names) for row in reply['current_regions']]

def regions(delta_refs, changes, exception):
    if exception != 'none':
        return []
    blocked = {p['region'] for p in changes if p['state'] not in ('retained_interactive', 'changed_interactive')}
    return list(dict.fromkeys([r for r in delta_refs if r not in blocked] + [p['region'] for p in changes if p['state'] in ('retained_interactive', 'changed_interactive')]))
