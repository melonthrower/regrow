from copy import deepcopy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919'

def load():
    spec = importlib.util.spec_from_file_location('resume_flow', ROOT/'stepwise_flow.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def fixture():
    m=load(); records={r:m.new_region(r,n) for r,n in [('main','主体'),('middle','中间区'),('menu','菜单')]}
    for r in records.values():
        r['controls']['open']={'name':'打开'+r['name'],'observations':[{'image_quality':'clear','image_quality_reason':'unobscured synthetic fixture','image':'crop.png','icon_description':'三个圆点','evidence':{'observation':'now'}}], 'action_refs':[]}
    def edge(source,target,attempt):
        records[source]['actions'][attempt]={'control':'open','operation':'tap','delivery':'executed_receipt_zero','result':{'exception':'none'},'evidence':{}}
        records[source]['transitions'].append({'source_control':'open','target_region':target,'attempt':attempt})
    edge('main','middle','a1');edge('middle','menu','a2');edge('main','menu','a3')
    state={'working_region':'menu','interactive_regions':['main'],'next_action_mode':'explore','observation':{'id':'now','control_refs':['open'],'image':'frame.png'}}
    return m,records,state

def test_shortest_directed_route_preserves_work_and_first_step_owner():
    m,r,s=fixture();before=deepcopy((r,s))
    q=m.assemble_context(ROOT,r,s,'menu')
    assert q['action_ready']
    assert len(q['navigation_path'])==1 and q['navigation_path'][0]['attempt']=='a3'
    assert q['source']['region']=='main' and q['source']['working_region']=='menu'
    assert q['backend_candidates'][0]['name']=='打开主体'
    assert '最短已知路径（1 步）' in q['dynamic_prompt']
    assert '主体 → 点击「打开主体」 → 菜单' in q['dynamic_prompt']
    assert '待继续探索区块：菜单' in q['dynamic_prompt']
    assert (r,s)==before

def test_multihop_and_no_invented_reverse_or_failed_edge():
    m,r,s=fixture();r['main']['actions']['a3']['result']['exception']='external_app'
    q=m.assemble_context(ROOT,r,s,'menu')
    assert len(q['navigation_path'])==2
    r['main']['actions']['a1']['delivery']='delivery_exception'
    q=m.assemble_context(ROOT,r,s,'menu')
    assert q['action_ready'] and '尚未记录到达路径' in q['dynamic_prompt']
    # Incoming indexes cannot create executable reverse paths.
    s['interactive_regions']=['menu'];s['working_region']='main'
    assert m.assemble_context(ROOT,r,s,'main')['action_ready']

def test_already_here_and_pending_exception_do_not_navigate():
    m,r,s=fixture();s['interactive_regions']=['menu']
    q=m.assemble_context(ROOT,r,s,'menu')
    assert q['action_ready'] and not q.get('navigation_path')
    s['interactive_regions']=['main'];s['next_action_mode']='recover_external'
    assert not m.assemble_context(ROOT,r,s,'menu')['action_ready']

def test_unavailable_first_control_blocks_route_and_cycles_terminate():
    m,r,s=fixture();r['middle']['transitions'].append({'source_control':'open','target_region':'main','attempt':'a2'})
    s['observation']['control_refs']=[]
    q=m.assemble_context(ROOT,r,s,'menu')
    assert q['action_ready'] and q['allow_back'] and not q['backend_candidates']


def test_navigation_advice_opens_alternative_current_regions():
    m,r,s=fixture();s['interactive_regions']=['main','middle']
    q=m.assemble_context(ROOT,r,s,'menu')
    assert {c['region_ref'] for c in q['backend_candidates']}=={'main','middle'}
    assert q['allow_back'] and q['navigation_advice']
    assert '更短' in q['system_prompt'] and '仅供参考' in q['dynamic_prompt']
    assert '此次仅选择路径第一步' not in q['dynamic_prompt']
    assert q['source']['return_to']=='menu'  # Intended goal; observed edges remain unchanged.


def test_off_route_control_binds_its_actual_owner(tmp_path):
    import numpy as np
    from PIL import Image
    m,r,s=fixture();s['interactive_regions']=['main','middle']
    frame=tmp_path/'frame.png'
    pixels=np.random.default_rng(19).integers(0,256,(160,160,3),dtype=np.uint8)
    Image.fromarray(pixels).save(frame)
    for rid,box in [('main',(10,10,45,45)),('middle',(80,80,120,120))]:
        image=tmp_path/(rid+'.png');Image.fromarray(pixels[box[1]:box[3],box[0]:box[2]]).save(image)
        r[rid]['controls']['open']['observations'][0]['image']=str(image)
    s['observation']['image']=str(frame)
    q=m.assemble_context(ROOT,r,s,'menu')
    binding=m.bind_action_target(q,{'target':'打开中间区','action':'click','x':100,'y':100})
    assert binding['status']=='matched'
    assert binding['region_ref']=='middle' and binding['working_region']=='menu'
    assert m.bind_action_target(q,{'target':'改写的入口描述','action':'click','x':100,'y':100})['control_ref']=='open'
    unregistered=m.bind_action_target(q,{'target':'未登记的关闭位置','action':'click','x':60,'y':60})
    assert unregistered['status']=='matched' and unregistered['control_ref'] is None
    assert m.bind_action_target(q,{'target':'系统返回','action':'back','x':None,'y':None})['status']=='matched'


def test_navigation_can_scroll_current_region_to_reach_goal(tmp_path):
    import numpy as np
    from PIL import Image
    m,r,s=fixture()
    frame=tmp_path/'panel.png'
    Image.fromarray(np.random.default_rng(19).integers(0,256,(100,100,3),dtype=np.uint8)).save(frame)
    r['main']['observations']=[{'image':str(frame)}]
    s['observation']['image']=str(frame)
    q=m.assemble_context(ROOT,r,s,'menu')
    proposal={'target':'主体','action':'scroll','x':50,'y':10,'end_x':50,'end_y':90,'reason':'收起面板以到达菜单'}
    binding=m.bind_action_target(q,proposal)
    assert binding['status']=='matched'
    assert binding['region_ref']=='main' and binding['working_region']=='menu'
    proposal['end_y']=110
    assert m.bind_action_target(q,proposal)['status']=='unresolved'


def test_navigation_discloses_recent_attempt_facts():
    m,r,s=fixture()
    r['main']['actions']['a3']['result']['description']='菜单再次打开，未到达目标'
    q=m.assemble_context(ROOT,r,s,'menu')
    assert '最近已执行动作及实际结果' in q['user_prompt']
    assert '菜单再次打开，未到达目标' in q['user_prompt']
    assert '不再原样重复' in q['user_prompt']


def test_navigation_input_and_scroll_need_no_task_or_crop(tmp_path):
    from PIL import Image
    m,r,s=fixture();frame=tmp_path/'frame.png';Image.new('RGB',(200,200)).save(frame)
    s['observation']['image']=str(frame)
    q=m.assemble_context(ROOT,r,s,'menu')
    q.update(region_image=None,backend_candidates=[])
    for action in ['input_text','scroll']:
        p={'action':action,'target':'search or list','x':30,'y':40,'text':'World','end_x':30,'end_y':100}
        assert m.bind_action_target(q,p)['status']=='matched'
    p={'action':'scroll','target':'list','x':30,'y':40,'end_x':300,'end_y':100}
    assert m.bind_action_target(q,p)['status']=='unresolved'
