from regrow.records.object_store import owned_actions
from regrow.records.object_store import observation_history
from regrow.records import object_store as object_store
'Build evidence records and import saved graphs without inventing outcomes.'
from regrow.records.object_store import owned_controls
from copy import deepcopy
from regrow.recognition import identity_templates as templates

def region_transitions(graph):
    """Project observed endpoints; do not infer causal effects or reverse paths.

    One action may reach multiple current Region candidates. Background changes
    remain annotations, never extra transitions. Source evidence stays immutable.
    """
    regions = {r['id'] for r in graph['regions']}
    controls = {c['id']: c for c in graph['controls']}
    result = []
    for edge in graph['action_edges']:
        if edge.get('delivery') != 'executed_receipt_zero' or edge.get('model_result', {}).get('status') != 'observed_effect':
            continue
        (source, control) = (edge['source_region'], edge['source_control'])
        if source not in regions or controls.get(control, {}).get('owner_ref') != source:
            raise ValueError('transition source is not the recorded control owner')
        for target in dict.fromkeys(edge['after_interactive_region_proposals']):
            if target not in regions:
                raise ValueError('unknown target Region')
            result.append({'source_region': source, 'source_control': control, 'target_region': target, 'attempt': edge['attempt'], 'relation': 'reaches_observed_interactive_candidate', 'before_observation': edge['before_observation'], 'after_observation': edge['after_observation'], 'before_image': edge['before_image'], 'after_image': edge['after_image'], 'selection_call': edge['selection_call'], 'result_call': edge['result_call'], 'interaction_scope_verified': edge.get('interaction_scope_verified', False), 'region_changes': deepcopy(edge.get('region_changes', [])), 'status': 'derived_from_executed_action_and_model_observation'})
    return result

def new_region(ref, name, description=''):
    return {'id': ref, 'name': name, 'description': description, 'parent_region': None, 'observations': [], 'controls': {}, 'functions': {}, 'actions': {}, 'transitions': []}

def region_observation(proposal, evidence, image=None):
    return {**{key: deepcopy(proposal[key]) for key in ('description', 'bbox', 'state_description') if key in proposal}, 'image': image, **templates.assessment(proposal), 'evidence': deepcopy(evidence)}

def control_observation(proposal, evidence, image=None, icon_image=None):
    fields = {'description': 'description', 'may_open_content':'may_open_content', 'needs_exploration':'needs_exploration', 'bbox': 'bbox', 'click_bbox': 'click_bbox'}
    return {**{dest: deepcopy(proposal[source]) for (dest, source) in fields.items() if source in proposal}, **templates.assessment(proposal), 'image': image, 'evidence': deepcopy(evidence)}

def control_name(proposal):
    return proposal.get('name') or proposal.get('text') or proposal.get('description') or '未命名控件'

def action_record(edge):
    evidence = {k: deepcopy(edge[k]) for k in ('before_observation', 'after_observation', 'before_image', 'after_image', 'selection_call', 'result_call') if k in edge}
    evidence['execution_dir'] = f"action_attempts/{edge['attempt']}"
    return {'control': edge['source_control'], 'delivery': edge.get('delivery', 'unconfirmed'), 'result': deepcopy(edge.get('model_result', {})), 'region_changes': [{'region': v['region_ref'], **{k: deepcopy(x) for (k, x) in v.items() if k != 'region_ref'}} for v in edge.get('region_changes', [])], 'interactive_regions': deepcopy(edge.get('after_interactive_region_proposals', [])), 'evidence': evidence}

def region_records(graph, observation_ref=None):
    """Import saved discovery evidence into the same records used by updates.

    A cutoff is for historical replay only; the maintained reader uses committed
    snapshots. No future action outcomes may leak into a replayed earlier frame.
    """
    observations = graph.get('observations', [])
    positions = {o['id']: i for (i, o) in enumerate(observations)}
    limit = positions[observation_ref] if observation_ref else len(observations) - 1
    included = observations[:limit + 1]
    known = {ref for o in included for ref in o.get('region_refs', [])}
    records = object_store.Records()
    for raw in graph['regions']:
        ref = raw['id']
        if observation_ref and ref not in known:
            continue
        prop = raw.get('proposal', {})
        r = new_region(ref, prop.get('name', ref), prop.get('description', ''))
        evidence = {k: raw[k] for k in ('observation', 'source_call', 'source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation'] = next((o['id'] for o in included if ref in o.get('region_refs', [])), None)
        observation_history(r).append(region_observation(prop, evidence, raw.get('crop')))
        observed = next((o for o in included if o['id'] == evidence['observation']), {})
        observation_history(r)[-1]['source_image'] = observed.get('frame')
        records[ref] = r
    for raw in graph['regions']:
        if raw['id'] not in records:
            continue
        parent = raw.get('proposal', {}).get('parent_index')
        if parent is not None:
            siblings = [v for v in graph['regions'] if v.get('source_call') == raw.get('source_call')]
            if not 0 <= parent < len(siblings):
                raise ValueError('invalid discovery parent index')
            records[raw['id']]['parent_region'] = siblings[parent]['id']
    for raw in graph['controls']:
        owner = raw['owner_ref']
        ref = raw['id']
        if owner not in records:
            continue
        if observation_ref and (not any((ref in o.get('control_refs', []) for o in included))):
            continue
        evidence = {k: raw[k] for k in ('observation', 'source_call', 'source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation'] = next((o['id'] for o in included if ref in o.get('control_refs', [])), None)
        prop = raw.get('proposal', {})
        owned_controls(records[owner])[ref] = {'name': control_name(prop), 'observations': [control_observation(prop, evidence, raw.get('control_crop'), raw.get('icon_crop'))]}
        for key in ('possible_purpose', 'may_open_content', 'needs_exploration', 'knowledge'):
            if key in prop:
                owned_controls(records[owner])[ref][key] = deepcopy(prop[key])
        if 'knowledge' in prop:
            observation_history(owned_controls(records[owner])[ref])[-1]['knowledge'] = prop['knowledge']
        for field in ('possible_operation', 'uncertainty'):
            if field in prop:
                observation_history(owned_controls(records[owner])[ref])[-1][field] = deepcopy(prop[field])
        observed = next((o for o in included if o['id'] == evidence['observation']), {})
        observation_history(owned_controls(records[owner])[ref])[-1]['source_image'] = observed.get('frame')
    for edge in graph.get('action_edges') or []:
        (source, control) = (edge['source_region'], edge['source_control'])
        (before, after) = (edge.get('before_observation'), edge.get('after_observation'))
        if before not in positions or (after is not None and after not in positions):
            raise ValueError('action references unknown observation')
        if after is not None and positions[after] > limit or (after is None and positions[before] >= limit):
            continue
        if source not in records or control not in owned_controls(records[source]):
            raise ValueError('action references unknown control or inconsistent Region owner')
        if any((t not in records for t in edge.get('after_interactive_region_proposals', []))):
            raise ValueError('unknown target Region')
        owned_actions(records[source])[edge['attempt']] = action_record(edge)
        if edge.get('delivery') == 'executed_receipt_zero' and edge.get('model_result', {}).get('status') == 'observed_effect':
            before_regions = observations[positions[before]].get('region_refs', [])
            changed = {v['region_ref'] for v in edge.get('region_changes', []) if v['state'] == 'changed_interactive'}
            for target in dict.fromkeys(edge.get('after_interactive_region_proposals', [])):
                if target in before_regions and target not in changed:
                    continue
                records[source]['transitions'].append({'source_control': control, 'target_region': target, 'attempt': edge['attempt'], 'relation': 'observed_interactive_candidate'})
    from regrow.records.record_history import image_record
    for record in [*records.values(), *records.controls.values()]:
        object_store.replace_observation_history(record, [image_record(row, legacy=True) for row in observation_history(record)])
    from regrow.records.control_records import normalize
    normalize(records)
    return records

def graph_state(graph, observation_ref=None):
    observations = graph['observations']
    obs = next((o for o in observations if o['id'] == observation_ref)) if observation_ref else observations[-1]
    return {'interactive_regions': obs.get('region_refs', []), 'next_action_mode': 'explore', 'observation': {'id': obs['id'], 'image': obs.get('frame'), 'control_refs': obs.get('control_refs', []), 'foreground': obs.get('foreground', {}), 'uncertainties': obs.get('uncertainties', [])}, 'action_history_supplied': graph.get('action_edges') is not None}
