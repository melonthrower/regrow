from types import SimpleNamespace
from tests.test_stepwise_resume_route import fixture,ROOT
from tests.test_recovery_discovery import mod


def test_changed_region_rechecks_unchanged_controls_visually(tmp_path):
    frame=tmp_path/'frame.png';frame.write_bytes(b'image')
    crop=tmp_path/'regions/r/back.png';crop.parent.mkdir(parents=True);crop.write_bytes(b'image')
    records={'r':{'controls':{'back':{'observations':[{'image':'back.png','evidence':{'source_call':'old'}}]}}}}
    m=mod('update_visibility');changes=[{'region':'r','state':'changed_interactive'}]
    assert m.locate_retained(records,changes,'new',tmp_path,frame,SimpleNamespace(locate=lambda *a:{'accepted':True}))==['back']
    assert m.locate_retained(records,changes,'new',tmp_path,frame,SimpleNamespace(locate=lambda *a:{'accepted':False}))==[]


def test_navigation_discloses_actual_control_results():
    flow,records,state=fixture()
    records['main']['controls']['open']['action_refs']=['a1']
    records['main']['actions']['a1']['result']['description']='只切换预览图标，仍在当前区块'
    q=flow.assemble_context(ROOT,records,state,'menu')
    assert '只切换预览图标，仍在当前区块' in q['user_prompt']
