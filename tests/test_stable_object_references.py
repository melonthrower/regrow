from copy import deepcopy
import jsonschema
import pytest

from regrow.recognition.control_references import prepare, decode
from regrow.records.object_store import Records, owned_controls, owned_tasks
from regrow.records.region_evidence import new_region
from regrow.records.object_knowledge import fields
from regrow.records.function_updates import apply as apply_functions
from regrow.records.shared_controls import propose_instances
from regrow.traversal.region_tasks import apply_plan
from regrow.traversal.action_binding import candidate_matches, candidate_key
from regrow.records.task_updates import resolve_suggestion


def records():
    result = Records({'r0001': new_region('r0001', '工具栏'),
                      'r0002': new_region('r0002', '工具栏')})
    for rid, cid in [('r0001','c0001'),('r0001','c0002'),('r0002','c0003')]:
        owned_controls(result[rid])[cid] = {'name':'添加', 'knowledge':[{'description':'打开添加入口'}]}
    return result


def test_stable_ids_disambiguate_tasks_actions_shared_controls_and_functions():
    r = records()
    reply = {'inventory':'complete','evidence':'已考虑给定对象','shared_instances':[],
             'function_updates':[], 'operations':[{'control':'c0002','task_type':'function',
             'completion_condition':'点击并记录结果即可。'}]}
    from regrow.records.registration_diagnostics import task_reference_errors
    assert task_reference_errors('task_proposal', {'source':{'region':'r0001'}}, reply, r)==[]
    apply_plan(r['r0001'],reply,'test',records=r,state={})
    assert next(iter(owned_tasks(r['r0001']).values()))['control']=='c0002'
    apply_functions(r,[{'region':'r0001','add':[{'name':'添加对象','description':'打开添加入口',
        'supports':['c0002']}]}], {'source_call':'test'})
    assert [s['control'] for s in r['r0001']['functions']['添加对象']['support_controls']]==['c0002']
    candidates=[{'id':'c0001','name':'添加','region_ref':'r0001'},
                {'id':'c0002','name':'添加','region_ref':'r0001'}]
    q={'source':{'region':'r0001'},'backend_candidates':candidates}
    assert candidate_key(q,candidates[1])=='c0002'
    assert candidate_matches(q,'c0002')==[candidates[1]]
    assert candidate_matches(q,'添加')==[]
    suggestion={'region':'r0001','control':'c0002','action':'click','reason':'探索'}
    assert resolve_suggestion(r,suggestion)['control']=='c0002'
    with pytest.raises(ValueError):resolve_suggestion(r,{**suggestion,'control':'添加'})
    changes=propose_instances(r,'r0002',[{'control':'c0003','source_region':'r0001',
        'source_control':'c0001','reason':'同一公共栏对象'}],'test',{})
    assert changes=={'c0003':'c0001'}
    assert owned_controls(r['r0002'])['c0001'] is owned_controls(r['r0001'])['c0001']


def test_boundary_keeps_refs_and_knowledge_item_indexes_distinct():
    r=records()
    q=prepare({'user_prompt':'工具栏[r0001] 添加[c0001] 添加[c0002]',
               'response_schema':{'type':'object','properties':fields(r,['r0001'])}})
    item=q['response_schema']['properties']['controls']['items']
    assert item['properties']['ref']['enum']==['c0001','c0002']
    assert 'index' not in item['properties'] and 'control_indexes' not in q
    reply={'controls':[{'ref':'c0002','knowledge':[{'index':0,'description':'修订用途'}]}]}
    original=deepcopy(reply)
    jsonschema.validate(reply,q['response_schema'])
    decoded=decode(q,reply)
    assert decoded['controls'][0]['ref']=='c0002'
    assert decoded['controls'][0]['knowledge'][0]['index']==0
    assert reply==original
    legacy={'control_indexes':['c0001','c0002']}
    assert decode(legacy,{'controls':[{'index':1,'knowledge':[]}]})['controls'][0]['ref']=='c0002'
    nested=prepare({'user_prompt':'c0001 c0002','response_schema':{'type':'object'},'original_request':legacy})
    assert nested['original_request']==legacy


def test_update_repair_retains_ref_only_objects_with_duplicate_names(monkeypatch):
    from regrow.traversal import repair_stages
    r = records()
    monkeypatch.setattr(repair_stages, '_record_load', lambda run: (None, r, {}))
    job = {'stage':'update', 'request':{'source':{'region':'r0001'},
           'region_names':{'r0001':'r0001'}},
           'candidate':{'controls':[{'ref':'c0002','knowledge':[]}]}}
    selected = repair_stages.related('.', job)
    assert set(owned_controls(selected['r0001'])) == {'c0002'}
