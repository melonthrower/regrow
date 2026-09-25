from tests.test_stepwise_region_tasks import tasks,fixture,row,proposal,ROOT
from tests.test_recovery_discovery import mod


def test_new_operation_review_invalidates_inventory_not_completed_tasks():
    _,records,_=fixture();r=records['menu'];m=tasks()
    m.apply_plan(r,proposal([row()]),'1');r['tasks']['查看内容']['status']='done'
    assert m.coverage(r)['complete']
    r['task_inventory']['review']={'reason':'刻度盘切换为可编辑字段','source_call':'2'}
    assert not m.coverage(r)['inventory_complete']
    assert r['tasks']['查看内容']['status']=='done'
    m.apply_plan(r,proposal([row('输入文字')]),'3')
    assert m.coverage(r)['inventory_complete']
    assert m.coverage(r)['pending']==['输入文字']


def test_materialization_records_explicit_review_reason():
    flow,records,_=fixture();r=records['menu']
    r['id']='r1';r['controls']={'c1':r['controls']['open']};records={'r1':r}
    r['task_inventory']={'inventory':'complete','controls':['c1']}
    reply={'regions':[{'name':'菜单','previous_name':'菜单','description':'输入模式','parent_index':None,
        'bbox':{'left':0,'top':0,'right':100,'bottom':100},'reason':'切换','task_review_reason':'已有控件从选择变为输入'}], 'controls':[]}
    mod('register_update').materialize_regions(records,reply,'new','update:new')
    assert r['task_inventory']['review']['reason']=='已有控件从选择变为输入'


def test_live_update_schema_requires_new_field():
    q=mod('update_step').build_update_request(ROOT,{},[])
    region=q['response_schema']['properties']['regions']['items']
    assert 'task_review_reason' in region['required']
