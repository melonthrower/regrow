import json
from copy import deepcopy
from pathlib import Path
import importlib.util
import jsonschema

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_visual_projection_does_not_promote_historical_semantics(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT))
    from PIL import Image
    frame=tmp_path/'history.png';im=Image.new('RGB',(40,40),'white');im.putpixel((1,1),(0,0,0));im.save(frame)
    row={'image':str(frame),'image_quality':'clear','image_quality_reason':'fixture identity pixels',
         'text':'Notifications','possible_operation':'Notify for app A','state':'on','evidence':{'observation':'old','source_call':'old-call'}}
    records={'r':{'controls':{'c':{'observations':[deepcopy(row)]}}}}
    state={'observation':{'id':'now'},'visual_navigation':{'observation':'now','controls':{'c':'r'}}}
    module('visual_backtrack').project(records,state)
    control=records['r']['controls']['c'];card=module('target_observation').describe(control,'now')
    assert '仅图片匹配' in card['观察来源'] and '未重新识别' in card['观察来源']
    assert control['observations'][0]==row
    assert control['observations'][-1]['semantic_source']==row['evidence']
    assert card['功能推测（未验证）']=='Notify for app A'
    # A registered observation remains a sourced clue; current state comes from the frame.
    control['observations'].append({**deepcopy(row),'evidence':{'observation':'new'}})
    fresh=module('target_observation').describe(control,'new')
    assert '最近登记观察' in fresh['观察来源'] and '看图核对' in fresh['观察来源']
    assert '文字' not in fresh and '可见状态' not in fresh


def test_recovery_complete_examples_match_wire_contract():
    m=module('recovery');lines=(ROOT/'遍历prompt/异常处理/恢复输出.prompt').read_text().splitlines()
    samples=[json.loads(x) for x in lines if x.startswith('{')]
    assert len(samples)==2
    for sample in samples:
        jsonschema.validate(sample,m.schema());m.validate(sample)


def test_loop_disclosure_names_and_progress_without_backend_ids():
    m=module('branch_switch')
    cause={'kind':'exploration_loop','repetitions':3,'cycle_length':1,'history':[
        {'work':'r123','position':['r123'],'task':None,'progress':'secret_hash'},
        {'work':'r123','position':['r123'],'task':None,'progress':'secret_hash'}]}
    original=deepcopy(cause)
    output=m.readable_trigger(cause,{'r123':{'name':'菜单'}})
    text=json.dumps(output,ensure_ascii=False)
    assert '菜单' in text and '记录摘要未变化' in text
    assert '旧记录未提供' in text and 'r123' not in text and 'secret_hash' not in text
    assert cause==original


def test_multihop_navigation_discloses_unregistered_targets_consistently():
    from tests.test_stepwise_resume_route import fixture
    m,records,state=fixture()
    records['main']['actions']['a3']['result']['exception']='external_app'
    q=m.assemble_context(ROOT,records,state,'menu')
    assert len(q['navigation_path'])==2
    assert '不要求已登记' in q['user_prompt']
    assert '入口未登记到当前前景时，用none' not in q['user_prompt']
