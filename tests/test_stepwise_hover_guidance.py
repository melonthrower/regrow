"""The existing three-step requests must carry observation gaps into preparation."""
from copy import deepcopy
import json

from PIL import Image
import pytest
from tests.test_recovery_discovery import ROOT, mod
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_resume_route import fixture


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))


def test_committed_observation_reaches_next_action_after_task_routing(tmp_path):
    run, _, discovery = setup(tmp_path)
    def seed(records, state, *_):
        state['handoff_summary'] = '菜单已打开；第二项被提示遮挡，外观尚未取得'
        state['observation']['uncertainties'] = ['移位是否会收起菜单尚未验证']
    discovery.publish(run, 'hover-handoff', seed)
    before = deepcopy(discovery.load(run)[1:])
    request = mod('stepwise_flow').assemble_current_context(ROOT, run)
    assert request['action_ready']
    assert '第二项被提示遮挡' in request['user_prompt']
    assert '移位是否会收起菜单尚未验证' in request['user_prompt']
    assert discovery.load(run)[1:] == before


def test_handoff_keeps_executed_parent_history_but_not_unexecuted_or_unrelated():
    _, records, state = fixture()
    state.update(interactive_regions=['menu'], working_region='menu')
    state['handoff_summary'] = '子菜单当前已收起'
    state['last_action_result'] = {'region': 'main', 'action': 'a0011'}
    records['main']['actions'] = {
        'a0010': {'control': 'open', 'operation': 'hover', 'delivery': 'executed_receipt_zero',
                  'result': {'description': '悬停入口后菜单展开'}, 'interactive_regions': ['menu']},
        'a0011': {'control': None, 'operation': 'hover', 'delivery': 'executed_receipt_zero',
                  'association': {'status': 'unconfirmed', 'target': '另一父项'},
                  'result': {'description': '移位后子菜单收起'}},
        'a0012': {'control': 'open', 'operation': 'click', 'delivery': 'unconfirmed',
                  'result': {'description': '尚未执行不能算已恢复'}}}
    records['middle']['actions'] = {'a0099': {'operation': 'click', 'delivery': 'executed_receipt_zero',
                                             'result': {'description': '无关窗口结果'}}}
    before = deepcopy((records, state))
    context = mod('page_history').build(records, state)
    text = json.dumps(context, ensure_ascii=False)
    assert '悬停入口后菜单展开' in text and '移位后子菜单收起' in text
    assert '另一父项' in text and 'unconfirmed' in text
    assert '尚未执行不能算已恢复' not in text and '无关窗口结果' not in text and '没有已执行回执' in text
    assert (records, state) == before


def test_task_inventory_receives_same_observation_gap():
    _, records, state = fixture()
    state['handoff_summary'] = '入口已完成，但新菜单的外观被提示遮挡'
    request = mod('region_tasks').plan_request(ROOT, records, state, 'menu')
    assert '入口已完成，但新菜单的外观被提示遮挡' in request['user_prompt']
    assert json.loads(request['user_prompt'])['区块'] == '菜单'


def test_desktop_guide_is_attached_without_mutating_request_or_schema():
    request = {'system_prompt': '原步骤规则', 'user_prompt': '{}', 'fixed_parts': [],
               'response_schema': {'type': 'object'}, 'role': 'observation_update'}
    original = deepcopy(request)
    sent = mod('desktop_transport').prepare_request(ROOT, request)
    assert any(p['path'] == '平台/桌面悬停观察.prompt' for p in sent['fixed_parts'])
    assert sent['response_schema'] == request['response_schema'] and request == original


def test_obscured_identity_does_not_replace_old_template_or_lose_click_area(tmp_path):
    frame = tmp_path / 'frame.png'; Image.new('RGB', (40, 40), 'red').save(frame)
    old = {'image': 'old.png', 'evidence': {'source_call': 'old'}}
    current = {'image': None, 'icon_image': None, 'evidence': {'source_call': 'new', 'source_field': 'controls/0'}}
    region = {'id': 'r', 'observations': [{'evidence': {'source_field': 'regions/0'}}],
              'controls': {'c': {'observations': [deepcopy(old), current]}}}
    click = dict(left=0, top=0, right=10, bottom=10)
    reply = {'regions': [{'bbox': None}], 'controls': [{'bbox': None, 'icon_bbox': None, 'click_bbox': click}]}
    mod('register_update').save_region_images({'r': region}, ['r'], reply, 'new', tmp_path,
        'frame.png', tmp_path/'snapshot', tmp_path/'temp')
    assert region['controls']['c']['observations'][0] == old
    assert current['image'] is None and current['icon_image'] is None
    assert current['click_bbox'] == click and current['click_image']
    assert not (tmp_path/'temp/regions/r/images/new/c.png').exists()


def test_failed_move_survives_reopen_with_receipt_backed_coordinates(tmp_path):
    _, records, state = fixture()
    state.update(interactive_regions=['menu'], last_action_result={'region':'main','action':'a0011'})
    state['handoff_summary'] = '菜单已重新打开'
    records['main']['actions'] = {
        'a0010': {'control': None, 'operation': 'hover', 'delivery': 'executed_receipt_zero',
                  'result': {'description': '移位导致菜单收起'}, 'interactive_regions': ['main']},
        'a0011': {'control': 'open', 'operation': 'click', 'delivery': 'executed_receipt_zero',
                  'result': {'description': '点击恢复菜单'}, 'interactive_regions': ['menu']}}
    folder = tmp_path/'action_attempts/a0010'; folder.mkdir(parents=True)
    (folder/'dispatch.json').write_text(json.dumps({'action': {'action':'hover','target':'另一父项','x':169,'y':154}}))
    (folder/'proposal.json').write_text(json.dumps({'action':'hover','x':999,'y':999}))
    (folder/'receipt.json').write_text(json.dumps({'exit_code':0}))
    helper = mod('page_history')
    text = json.dumps(helper.build(records, state, tmp_path), ensure_ascii=False)
    assert all(s in text for s in ('移位导致菜单收起','点击恢复菜单','169','154'))
    assert '999' not in text
    (folder/'receipt.json').write_text(json.dumps({'exit_code':1}))
    assert '169' not in json.dumps(helper.build(records, state, tmp_path), ensure_ascii=False)
