"""Shared-conflict prompt contract, alongside native saved-record acceptance."""
from tests.test_recovery_discovery import mod, ROOT
from tests.test_shared_control_conflict_repair import conflicting


def test_shared_conflict_request_is_text_only_and_has_no_unrelated_manual(tmp_path):
    m=mod('shared_control_review');records=conflicting()
    q=m.build_request(ROOT,tmp_path,tmp_path,records,{},m.conflicts(records)[0])
    job={'stage':'shared_control_review','request':q,'history':[],'error':'共享结果不同','repairs':0}
    sent=mod('step_repair').request(ROOT,job,{})
    assert sent['screenshots']==[]
    assert [p['path'] for p in sent['fixed_parts']]==['纠错/共享行为核对.prompt']
    assert 'shared_behavior' in sent['system_prompt']
    assert '原任务要求' not in sent['user_prompt']
    assert 'World' not in sent['system_prompt']
    assert '实际结果' in sent['user_prompt']
    assert sent['response_schema']['properties']['resolution']['enum']==['edit_record','blocked']


def test_shared_retry_keeps_rejected_edit_and_actual_error(tmp_path):
    m=mod('shared_control_review');records=conflicting();q=m.build_request(ROOT,tmp_path,tmp_path,records,{},m.conflicts(records)[0])
    job={'stage':'shared_control_review','request':q,'repairs':1,'error':'成员名称不唯一','last_shared_reply':{'record_edit':{'region':'wrong'}}}
    sent=mod('step_repair').request(ROOT,job,{})
    assert '成员名称不唯一' in sent['user_prompt'] and 'wrong' in sent['user_prompt']
    assert sent['screenshots']==[]


def test_only_non_gui_shared_repair_omits_environment_action_manual(tmp_path):
    m=mod('shared_control_review');r=conflicting();q=m.build_request(ROOT,tmp_path,tmp_path,r,{},m.conflicts(r)[0])
    sent=mod('step_repair').request(ROOT,{'stage':'shared_control_review','request':q,'repairs':0},{})
    transport=mod('recover_external')
    assert transport.with_environment_scope(ROOT,sent)==sent
    other={**sent,'original_request':{'stage':'action'}}
    assert any(p['path']=='平台/遍历环境只读.prompt' for p in transport.with_environment_scope(ROOT,other)['fixed_parts'])


def test_shared_parse_retry_keeps_unparseable_reply(tmp_path):
    m=mod('shared_control_review');r=conflicting();q=m.build_request(ROOT,tmp_path,tmp_path,r,{},m.conflicts(r)[0])
    job={'stage':'shared_control_review','request':q,'repairs':1,'error':'invalid JSON','parse_failure':{'reason':'invalid JSON','raw':'{broken output'}}
    sent=mod('step_repair').request(ROOT,job,{})
    assert '{broken output' in sent['user_prompt']
