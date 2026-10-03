"""Routes remain advisory after removing unregistered GUI replay."""
from tests.test_stepwise_resume_route import fixture, ROOT


def test_prompt_discloses_future_buttons_as_history_not_current_targets():
    m,records,state=fixture();records['main']['actions'].pop('a3');records['main']['transitions']=records['main']['transitions'][:1]
    q=m.assemble_context(ROOT,records,state,'menu')
    assert '后续入口参考' in q['user_prompt'] and '打开中间区' in q['user_prompt']
    assert '尚未确认当前可操作' in q['user_prompt']
    assert {c['region_ref'] for c in q['backend_candidates']}=={'main'}
