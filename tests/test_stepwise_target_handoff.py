from copy import deepcopy
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_deferral import setup


def test_text_target_uses_current_frame_and_labels_old_appearance():
    c={'name':'Search','observations':[
       {'icon_description':'顶部文字','evidence':{'observation':'old'}},
       {'text':'Search','icon_description':'','state':'位于返回箭头右侧',
        'uncertainty':'输入功能未验证','evidence':{'observation':'now'}}]}
    m=tasks().helper('target_observation');before=deepcopy(c)
    card=m.describe(c,'now')
    assert '可见状态' not in card and '本轮截图' in card['当前状态依据']
    assert card['历史外观参考']=='顶部文字'
    assert card['本次外观']=='' and card['功能疑问']=='输入功能未验证'
    assert '历史' in m.describe(c,'missing')['观察来源']
    assert c==before


def test_action_and_repair_receive_same_target_observation(tmp_path):
    run,q,d=setup(tmp_path)
    def seed(records,state,*args):
        c=records['r1']['controls']['c1'];v=c['observations'][-1]
        v.update(icon_description='',state='顶部文字入口',uncertainty='是否输入未验证')
        v['evidence']['observation']=state['observation']['id']
    d.publish(run,'target-observation',seed)
    _,records,state=d.load(run);q['source']['observation']=state['observation']['id']
    q.update(action_ready=True,backend_candidates=[{'id':'c1','name':'Policy'}],user_prompt='任务',dynamic_prompt='任务')
    m=tasks().helper('target_observation');q=m.attach(q,records)
    assert '顶部文字入口' not in q['user_prompt']
    assert '是否输入未验证' in q['user_prompt'] and q['image_refs']
    ctx=tasks().helper('repair_stages').context(run,{'stage':'action','request':q})
    assert ctx['区块'][0]['控件'][0]['目标观察']==q['target_observations'][0]['目标观察']
    assert len(q['target_observations'])==1
