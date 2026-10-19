"""Parameter prose survives validation, persistence, reread and invalidation."""
from copy import deepcopy
import pytest
from regrow.records import tasks, task_settlement
from regrow.records.control_knowledge import parameters
from regrow.records.object_store import Records, owned_tasks

def case():
    records=Records({'r1':{'id':'r1','name':'Panel','controls':{'c1':{'name':'Month'}},'tasks':{'范围':{'name':'范围','control':'c1','task_type':'parameter','status':'pending'}}}})
    return records,owned_tasks(records['r1'])['范围']

def fact(description='接受 1 至 12 的整数。'):
    return dict(name='月份',description=description)

def test_text_answer_roundtrip_and_invalidation():
    records,task=case();f=fact()
    accepted,gaps=task_settlement.partition_findings([f],task)
    assert accepted==[f] and gaps==[]
    tasks.store_findings(task,accepted,{'basis':'explored','attempt':'a1'})
    assert tasks.read(task,'findings')['月份']['description']==f['description']
    tasks.store_findings(task,[fact('接受 1 至 12 的整数；可以清空。')],{'basis':'explored','attempt':'a2'})
    control=tasks.target(task)
    assert 'domain' not in parameters(control)['月份']
    tasks.invalidate_products(control,'a2',{'source_call':'3'})
    assert parameters(control)['月份']['description']==f['description']
    assert tasks.read(task,'findings')['月份']['description']==f['description']

@pytest.mark.parametrize('change',[{'description':' '},{'evidence':'重复历史'},{'conditions':[]},{'domain':{'type':'text','values':[],'min':None,'max':None}}])
def test_reject_empty_prose_and_retired_output_field(change):
    accepted,gaps=task_settlement.partition_findings([{**fact(),**change}])
    assert accepted==[] and len(gaps)==1

def test_merge_does_not_silently_discard_different_prose():
    first={'constraints':{'月份':fact()}}
    second={'constraints':{'月份':fact('接受 1 至 6 的整数。')}}
    with pytest.raises(ValueError):tasks.merge_products(deepcopy(first),second)

def test_old_domain_remains_readable_until_new_answer():
    records,task=case();old={**fact(),'domain':{'type':'integer','values':[],'min':1,'max':12}}
    tasks.store_findings(task,[old],{'basis':'explored','attempt':'a1'})
    assert tasks.read(task,'findings')['月份']['domain']['max']==12
    tasks.store_findings(task,[fact()],{'basis':'explored','attempt':'a2'})
    assert 'domain' not in tasks.read(task,'findings')['月份']


def test_history_does_not_invent_missing_retired_domain():
    from regrow.records.history_context import task_goal
    records,task=case()
    tasks.store_findings(task,[fact()],{'basis':'explored','attempt':'a1'})
    goal=task_goal(task,records)
    import json
    assert 'domain' not in json.dumps(goal)
    assert 'conditions' not in json.dumps(goal)


def test_old_condition_variants_are_not_overwritten():
    records,task=case()
    old={**fact('编辑已有日期。'),'conditions':['编辑模式']}
    tasks.store_findings(task,[old],{'basis':'explored','attempt':'a1'})
    tasks.store_findings(task,[fact('编辑模式下修改日期；新建模式下填写日期。')],{'basis':'explored','attempt':'a2'})
    values=tasks.read(task,'findings')
    assert values['月份']['conditions']==['编辑模式']
    assert values['月份 / 综合描述']['description'].startswith('编辑模式')
    assert 'conditions' not in values['月份 / 综合描述']


def test_function_summary_preserves_condition_in_prose():
    from regrow.traversal import region_functions
    from regrow.paths import SOURCE_ROOT
    import jsonschema
    records,task=case();task['status']='done'
    description='开启自定义日期后可编辑，接受 1 至 12 的整数。'
    tasks.store_findings(task,[fact(description)],{'basis':'explored','attempt':'a1','region':'r1','control':'c1'})
    region=records['r1']
    from regrow.records.object_store import region_work
    region_work(region)['task_inventory']={'inventory':'complete','controls':['c1']}
    ref=next(iter(region_functions.catalog(region,records)))
    support=next(iter(region_functions.support_catalog(region,records)))
    reply={'functions':[{'name':'设置日期','description':'编辑日期','object':'日期','completion':'月份已填写','supports':[support],'constraints':[ref],'unconfirmed':[]}],
           'parameter_definitions':[{'ref':ref,'description':description}], 'evidence':'已有参数记录', 'local_knowledge':{}}
    jsonschema.validate(reply,region_functions.request_schema(SOURCE_ROOT,region,records))
    region_functions.register(region,reply,'summary',records)
    saved=region['functions']['设置日期']['constraints'][ref]
    assert saved['description']==description
    assert 'conditions' not in saved


def test_framework_sources_survive_without_model_evidence():
    records,task=case();source={'basis':'explored','attempt':'a1','region':'r1','control':'c1','source_call':'01'}
    tasks.store_findings(task,[fact()],source)
    saved=tasks.read(task,'findings')['月份']
    assert saved['source']['attempt']=='a1'
    assert saved['source']['source_call']=='01'
    assert saved['source']['task_ref']==task.ref
    assert 'evidence' not in saved['source']
    from regrow.records.history_context import task_goal
    goal=task_goal(task,records)
    import json
    assert '"原观察缺失字段":' not in json.dumps(goal,ensure_ascii=False)


def test_historical_evidence_text_is_still_readable():
    records,task=case()
    tasks.store_findings(task,[{**fact(),'evidence':'旧试验：输入 0 后报错。'}],{'basis':'explored','attempt':'a1'})
    assert tasks.read(task,'findings')['月份']['source']['evidence']=='旧试验：输入 0 后报错。'
