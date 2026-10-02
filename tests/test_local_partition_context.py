"""Read-only same-frame partitions constrain local publication, not identity decisions."""
import json
from PIL import Image
from tests.test_recovery_discovery import mod, ROOT


def context(tmp_path):
    frame=tmp_path/'frame.png';Image.new('RGB',(100,100)).save(frame)
    records={'nav':{'name':'导航','description':'页面导航','controls':{'back':{'name':'返回','observations':[]}}},
             'body':{'name':'内容','description':'设置列表','controls':{}}}
    scope={'region_bounds':{'nav':[0,0,100,20],'body':[0,20,100,100]},'source_call':'global'}
    ranking={'nav':{'anchors':[{'control':'back','box':[5,5,15,15],'accepted':True,'score':1}]}}
    return records,mod('local_partition').build(records,'body',frame,scope,ranking)


def proposal(bounds=(0,20,100,100),control=(5,30,15,40)):
    box=lambda b:dict(zip(('left','top','right','bottom'),b))
    return {'regions':[{'name':'内容','bbox':box(bounds)}],
            'controls':[{'name':'按钮','identity':'new','region_index':0,'bbox':box(control),'click_bbox':None}]}


def test_other_owner_context_is_read_only_and_has_current_coordinates(tmp_path):
    records,partition=context(tmp_path);m=mod('local_partition')
    text=m.prompt(partition)
    assert text['本区块已确认边界']==[0,20,100,100]
    assert text['其他已确认区块'][0]['已匹配控件'][0]['当前候选位置']==[5,5,15,15]
    assert text['其他已确认区块'][0]['名称']=='导航'
    assert partition['source_call']=='global'
    assert not m.errors({'discovery_context':{'partition_context':partition}},proposal())


def test_expansion_and_cross_owner_control_are_both_reported(tmp_path):
    _,partition=context(tmp_path);q={'discovery_context':{'partition_context':partition}}
    errors=mod('local_partition').errors(q,proposal((0,0,100,100),(6,6,14,14)))
    assert {e['code'] for e in errors}=={'local_region_bounds','local_control_owner','local_control_duplicate'}
    assert any(e['path']=='/regions/0/bbox' for e in errors)
    assert any('导航' in str(e) and '返回' in str(e) for e in errors)


def test_similar_arrow_on_another_page_is_not_an_identity_or_guard(tmp_path):
    records,partition=context(tmp_path)
    records['oldpage']={'name':'旧页导航','description':'旧页','controls':{'oldback':{'name':'返回'}}}
    scope={'region_bounds':{'body':[0,20,100,100]}}
    fresh=mod('local_partition').build(records,'body',tmp_path/'frame.png',scope,
        {'oldpage':{'anchors':[{'control':'oldback','box':[5,30,15,40],'accepted':True,'score':1}]}})
    assert not mod('local_partition').errors({'discovery_context':{'partition_context':fresh}},proposal())


def test_native_prompt_keeps_focus_write_scope(tmp_path,monkeypatch):
    records,partition=context(tmp_path)
    for rid,r in records.items():r.update(id=rid,tasks={},observations=[])
    m=mod('discovery_step');reg=m.registration();sibling=reg.sibling
    locator=sibling('visual_region_locator')
    monkeypatch.setattr(locator,'plan',lambda *a,**k:dict(mode='local',focus='body',regions=[],controls=[],next_offset=0,partition_context=partition))
    reg.sibling=lambda n:locator if n=='visual_region_locator' else sibling(n)
    monkeypatch.setattr(m,'registration',lambda:reg)
    q=m.prepare(ROOT,records,{'working_region':'body'},str(tmp_path/'frame.png'))
    text=json.loads(q['user_prompt'])
    assert text['同帧已确认区块划分']['其他已确认区块'][0]['名称']=='导航'
    assert 'back' not in q['discovery_context']['control_names'].values()
    assert q['response_schema']['properties']['regions']['maxItems']==1


def test_supplement_keeps_partition_context(tmp_path):
    records,partition=context(tmp_path)
    m=mod('discovery_step')
    for rid,r in records.items():r.update(id=rid,tasks={},observations=[])
    q={'discovery_context':{'mode':'local','focus':'body','region_names':{'内容':'body'},'control_names':{},'partition_context':partition},
       'user_prompt':'{}','system_prompt':'','response_schema':m.schema(ROOT,'local'),'fixed_parts':[]}
    batch={'frame':str((tmp_path/'frame.png').resolve()),'sha256':mod('discovery_completion').fingerprint(tmp_path/'frame.png'),
           'request':q,'pending':[{'item':'按钮','proposal':{'name':'按钮','description':'未确认'}}],'regions':['body'],'controls':[]}
    result=mod('discovery_completion').supplement(ROOT,records,{'discovery_completion':batch},str(tmp_path/'frame.png'))
    assert json.loads(result['user_prompt'])['同帧已确认区块划分']['本区块已确认边界']==[0,20,100,100]
    assert result['discovery_context']['partition_context']==partition
    guidance=json.loads(result['user_prompt'])['同帧已确认区块划分']['用途']
    assert 'unresolved' in guidance and '不能直接' in guidance
    assert 'not_interactive' not in guidance
