import json,sys
from types import SimpleNamespace
import pytest
from tests.test_recovery_discovery import mod


def fixture(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda a,b:True))
    records={'r':{'tasks':{'verify':{'status':'pending','attempts':['a','b']}},'actions':{}}}
    for aid in ['a','b']:
        folder=tmp_path/'action_attempts'/aid;folder.mkdir(parents=True)
        (folder/'proposal.json').write_text(json.dumps({'action':'click'}))
        (folder/'binding.json').write_text(json.dumps({'region_ref':'r','control_ref':'back'}))
        records['r']['actions'][aid]={'delivery':'executed_receipt_zero','interactive_regions':['other'],'result':{'exception':'none','description':'回到其他页面'}}
    return records,{'region_ref':'r','control_ref':'back','task_region':'r','task_name':'verify'}


def test_repeated_successful_navigation_enters_correction_not_automatic_defer(tmp_path,monkeypatch):
    r,b=fixture(tmp_path,monkeypatch);m=mod('attempt_guard')
    # Source is stable; the action did change the page, so old no-effect guard misses it.
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda a,b:a.name=='before.png'))
    with pytest.raises(ValueError,match='重复导航') as error:m.check(tmp_path,r,b,{'action':'click'},tmp_path/'current.png')
    assert not getattr(error.value,'defer_task',False)


def test_changed_source_or_different_destination_is_not_same_cycle(tmp_path,monkeypatch):
    r,b=fixture(tmp_path,monkeypatch);m=mod('attempt_guard')
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda *a:False))
    m.check(tmp_path,r,b,{'action':'click'},tmp_path/'current.png')
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda a,b:a.name=='before.png'))
    r['r']['actions']['b']['interactive_regions']=['different']
    m.check(tmp_path,r,b,{'action':'click'},tmp_path/'current.png')


def test_history_dependent_return_is_not_a_fixed_navigation_cycle(tmp_path,monkeypatch):
    r,b=fixture(tmp_path,monkeypatch);m=mod('attempt_guard')
    monkeypatch.setitem(sys.modules,'visual_backtrack',SimpleNamespace(same_surface=lambda a,b:a.name=='before.png'))
    for a in r['r']['actions'].values():a['result']['returns_to_previous']=True
    m.check(tmp_path,r,b,{'action':'click'},tmp_path/'current.png')
