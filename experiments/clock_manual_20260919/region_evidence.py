"""Build evidence records and import saved graphs without inventing outcomes."""
from copy import deepcopy
import identity_templates as templates


def region_transitions(graph):
    """Project observed endpoints; do not infer causal effects or reverse paths.

    One action may reach multiple current Region candidates. Background changes
    remain annotations, never extra transitions. Source evidence stays immutable.
    """
    regions = {r['id'] for r in graph['regions']}
    controls = {c['id']:c for c in graph['controls']}
    result = []
    for edge in graph['action_edges']:
        if (edge.get('delivery') != 'executed_receipt_zero'
                or edge.get('model_result', {}).get('status') != 'observed_effect'):
            continue
        source, control = edge['source_region'], edge['source_control']
        if source not in regions or controls.get(control, {}).get('owner_ref') != source:
            raise ValueError('transition source is not the recorded control owner')
        for target in dict.fromkeys(edge['after_interactive_region_proposals']):
            if target not in regions:
                raise ValueError('unknown target Region')
            result.append({
                'source_region':source, 'source_control':control,
                'target_region':target, 'attempt':edge['attempt'],
                'relation':'reaches_observed_interactive_candidate',
                'before_observation':edge['before_observation'],
                'after_observation':edge['after_observation'],
                'before_image':edge['before_image'], 'after_image':edge['after_image'],
                'selection_call':edge['selection_call'], 'result_call':edge['result_call'],
                'interaction_scope_verified':edge.get('interaction_scope_verified', False),
                'region_changes':deepcopy(edge.get('region_changes', [])),
                'status':'derived_from_executed_action_and_model_observation',
            })
    return result



def new_region(ref, name, description=''):
    return {'id':ref, 'name':name, 'description':description, 'parent_region':None,
            'observations':[], 'controls':{}, 'functions':{}, 'actions':{},
            'transitions':[], 'reached_by':[]}



def region_observation(proposal, evidence, image=None):
    # Current-frame position is evidence even when the appearance is occluded.
    # Template admission remains independent in identity_templates.
    return {'description':proposal.get('description',''), 'reason':proposal.get('reason',''),
            'controls_complete':proposal.get('controls_complete',False),
            'bbox':deepcopy(proposal.get('bbox')),
            'image':image, **templates.assessment(proposal), 'evidence':deepcopy(evidence)}



def control_observation(proposal, evidence, image=None, icon_image=None):
    return {'text':proposal.get('text',''), 'icon_description':proposal.get('icon_appearance',''),
            'state':proposal.get('state',''), 'possible_operation':proposal.get('possible_operation',''),
            'uncertainty':proposal.get('uncertainty',''), **templates.assessment(proposal), 'image':image, 'icon_image':icon_image,
            'bbox':deepcopy(proposal.get('bbox')),
            **({'click_bbox':deepcopy(proposal['click_bbox'])} if 'click_bbox' in proposal else {}),
            'evidence':deepcopy(evidence)}



def control_name(proposal):
    return proposal.get('name') or proposal.get('text') or proposal.get('icon_appearance') or '未命名控件'



def action_record(edge):
    # Preserve legacy assessments as reported; never invent exception=none.
    evidence = {k:deepcopy(edge[k]) for k in ('before_observation','after_observation',
                'before_image','after_image','selection_call','result_call') if k in edge}
    evidence['execution_dir'] = f"action_attempts/{edge['attempt']}"
    return {'control':edge['source_control'], 'delivery':edge.get('delivery','unconfirmed'),
            'result':deepcopy(edge.get('model_result',{})),
            'region_changes':[{'region':v['region_ref'], **{k:deepcopy(x) for k,x in v.items() if k!='region_ref'}}
                              for v in edge.get('region_changes',[])],
            'interactive_regions':deepcopy(edge.get('after_interactive_region_proposals',[])),
            'evidence':evidence}



def index_actions(records):
    for r in records.values():
        for cid,c in r['controls'].items():
            c['action_refs']=[aid for aid,a in r['actions'].items() if a['control']==cid]



def region_records(graph, observation_ref=None):
    """Import saved discovery evidence into the same records used by updates.

    A cutoff is for historical replay only; the maintained reader uses committed
    snapshots. No future action outcomes may leak into a replayed earlier frame.
    """
    observations=graph.get('observations',[])
    positions={o['id']:i for i,o in enumerate(observations)}
    limit=positions[observation_ref] if observation_ref else len(observations)-1
    included=observations[:limit+1]
    known={ref for o in included for ref in o.get('region_refs',[])}
    records={}
    for raw in graph['regions']:
        ref=raw['id']
        if observation_ref and ref not in known:continue
        prop=raw.get('proposal',{})
        r=new_region(ref,prop.get('name',ref),prop.get('description',''))
        evidence={k:raw[k] for k in ('observation','source_call','source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation']=next((o['id'] for o in included if ref in o.get('region_refs',[])),None)
        r['observations'].append(region_observation(prop,evidence,raw.get('crop')))
        observed=next((o for o in included if o['id']==evidence['observation']),{})
        r['observations'][-1]['source_image']=observed.get('frame')
        records[ref]=r
    for raw in graph['regions']:
        if raw['id'] not in records:continue
        parent=raw.get('proposal',{}).get('parent_index')
        if parent is not None:
            siblings=[v for v in graph['regions'] if v.get('source_call')==raw.get('source_call')]
            if not 0<=parent<len(siblings):raise ValueError('invalid discovery parent index')
            records[raw['id']]['parent_region']=siblings[parent]['id']
    for raw in graph['controls']:
        owner=raw['owner_ref'];ref=raw['id']
        if owner not in records:continue
        if observation_ref and not any(ref in o.get('control_refs',[]) for o in included):continue
        evidence={k:raw[k] for k in ('observation','source_call','source_field') if k in raw}
        if 'observation' not in evidence:
            evidence['observation']=next((o['id'] for o in included if ref in o.get('control_refs',[])),None)
        prop=raw.get('proposal',{})
        records[owner]['controls'][ref]={'name':control_name(prop),
            'observations':[control_observation(prop,evidence,raw.get('control_crop'),raw.get('icon_crop'))], 'action_refs':[]}
        observed=next((o for o in included if o['id']==evidence['observation']),{})
        records[owner]['controls'][ref]['observations'][-1]['source_image']=observed.get('frame')
    for edge in graph.get('action_edges') or []:
        source,control=edge['source_region'],edge['source_control']
        before,after=edge.get('before_observation'),edge.get('after_observation')
        if before not in positions or (after is not None and after not in positions):
            raise ValueError('action references unknown observation')
        if (after is not None and positions[after]>limit) or (after is None and positions[before]>=limit):continue
        if source not in records or control not in records[source]['controls']:
            raise ValueError('action references unknown control or inconsistent Region owner')
        if any(t not in records for t in edge.get('after_interactive_region_proposals',[])):
            raise ValueError('unknown target Region')
        records[source]['actions'][edge['attempt']]=action_record(edge)
        if edge.get('delivery')=='executed_receipt_zero' and edge.get('model_result',{}).get('status')=='observed_effect':
            before_regions=observations[positions[before]].get('region_refs',[])
            changed={v['region_ref'] for v in edge.get('region_changes',[]) if v['state']=='changed_interactive'}
            for target in dict.fromkeys(edge.get('after_interactive_region_proposals',[])):
                if target in before_regions and target not in changed:continue
                records[source]['transitions'].append({'source_control':control,'target_region':target,
                    'attempt':edge['attempt'],'relation':'observed_interactive_candidate'})
                records[target]['reached_by'].append({'source_region':source,'source_control':control,'attempt':edge['attempt']})
    index_actions(records)
    return records



def graph_state(graph, observation_ref=None):
    observations=graph['observations']
    obs=next(o for o in observations if o['id']==observation_ref) if observation_ref else observations[-1]
    return {'interactive_regions':obs.get('region_refs',[]), 'next_action_mode':'explore',
            'observation':{'id':obs['id'],'image':obs.get('frame'),
                'control_refs':obs.get('control_refs',[]),'foreground':obs.get('foreground',{}),
                'uncertainties':obs.get('uncertainties',[])},
            'action_history_supplied':graph.get('action_edges') is not None}
