from copy import deepcopy
from tests.test_recovery_discovery import mod


def records():
    f=mod('stepwise_flow')
    return {r:f.new_region(r,'菜单',d) for r,d in [('r0001','编辑操作，复制与粘贴'),('r0002','列表操作，排序与筛选')]}


def test_visual_hit_keeps_record_identity(tmp_path):
    from tests.test_stepwise_update_region_matching import case
    m,rs,reply=case(tmp_path)
    hits=m.candidates(rs,tmp_path,tmp_path/'after.png')
    assert hits and hits[0]['region_ref']=='r0001'


def test_same_name_never_transfers_visual_reason_or_position():
    rs=records();hits=[{'region_ref':'r0001','name':'菜单','bbox':[1,2,30,40],'score':1}]
    m=mod('history_context');names=mod('region_candidate_names')
    rows=m.identity_candidates(rs,{'interactive_regions':['r0002']},{'region_ref':'r0002'},hits)
    assert {x['region_ref'] for x in rows}==set(rs)
    projected,mapping=names.candidates(rs,rows)
    by_id={mapping[x['name']]:x for x in projected}
    assert '截图外观匹配候选（不等于前景）' in by_id['r0001']['提供原因']
    assert '截图外观匹配候选（不等于前景）' not in by_id['r0002']['提供原因']
    assert '动作前来源' not in by_id['r0001']['提供原因']
    assert '动作前来源' in by_id['r0002']['提供原因']
    assert all('region_ref' not in x for x in projected)
    assert names.candidates(dict(reversed(list(rs.items()))),rows)==(projected,mapping)


def test_name_only_ambiguous_hit_is_not_visual_evidence():
    rs=records();m=mod('history_context')
    rows=m.identity_candidates(rs,{}, {'region_ref':'r0001'},[{'name':'菜单'}])
    assert rows
    assert all('截图外观匹配候选（不等于前景）' not in x['提供原因'] for x in rows)


def test_semantic_rename_keeps_actions_tasks_and_graph_references():
    rs=records();row=[{'region_ref':r,'name':v['name']} for r,v in rs.items()]
    _,names=mod('region_candidate_names').candidates(rs,row)
    old=next(n for n,r in names.items() if r=='r0001')
    rs['r0001']['actions']={'a1':{'operation':'click'}}
    rs['r0001']['tasks']={'查看菜单':{'status':'pending'}}
    rs['r0002']['transitions']=[{'destination_region':'r0001'}]
    before=deepcopy(rs)
    reply={'regions':[{'name':'编辑菜单','previous_name':old,'description':'编辑操作，复制与粘贴','reason':'与排序菜单职责不同','parent_index':None,'bbox':None}], 'controls':[]}
    refs=mod('register_update').materialize_regions(rs,reply,'new','obs',names)
    assert refs==['r0001'] and rs['r0001']['name']=='编辑菜单'
    assert rs['r0001']['actions']==before['r0001']['actions']
    assert rs['r0001']['tasks']==before['r0001']['tasks']
    assert rs['r0002']==before['r0002']


def test_discovery_alias_is_not_persisted_and_explicit_rename_is(tmp_path):
    import json
    from tests.test_recovery_discovery import seeded_run,discovery_reply,ROOT
    for new_name in ['Menu — 编辑操作','编辑菜单']:
        base=tmp_path/str(len(list(tmp_path.iterdir())));base.mkdir()
        m=mod('discovery_step');run=seeded_run(base);m.await_discovery(run,'returned.png','review')
        q=m.request_from_run(ROOT,run);q['discovery_context']['region_names']={'Menu — 编辑操作':'r1'}
        reply=discovery_reply();reply['regions'][0].update(name=new_name,previous_name='Menu — 编辑操作')
        before=deepcopy(m.load(run)[1]['r1'])
        call=run/'calls/0003';call.mkdir()
        (call/'request.json').write_text(json.dumps(q));(call/'response.json').write_text(json.dumps(reply))
        m.commit(ROOT,run,'0003');r=m.load(run)[1]['r1']
        assert r['name']==('Menu' if new_name=='Menu — 编辑操作' else new_name)
        assert r['actions']==before['actions'] and r.get('tasks',{})==before.get('tasks',{})
