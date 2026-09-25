from copy import deepcopy
from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def seed(records, state, *args):
    r = records['r1']
    r['tasks']['Policy'].update(attempts=['a7'], result_evidence='输入功能尚未确认')
    r['actions']['a7'] = {'control': 'c1', 'operation': 'click',
        'delivery': 'executed_receipt_zero', 'result': {'description': '点击后仍为空状态'}}


def test_pending_attempt_is_disclosed_without_changing_completion(tmp_path):
    run, q, d = setup(tmp_path)
    d.publish(run, 'attempt', seed)
    records = d.load(run)[1]
    before = deepcopy(records)
    text = tasks().render(records['r1'], records)
    assert '点击后仍为空状态' in text and '输入功能尚未确认' in text
    assert 'click' in text and '已执行' in text and '待完成' in text
    assert 'a7' not in text
    assert records == before
    ctx = tasks().helper('repair_stages').context(run, {'stage': 'action', 'request': q})
    assert '点击后仍为空状态' in str(ctx['区块'][0]['任务'])
    assert len(ctx['区块'][0]['任务']) == 1


def test_cross_region_attempt_and_missing_record_remain_honest(tmp_path):
    run, q, d = setup(tmp_path)
    def cross(records, state, *args):
        seed(records, state)
        r = records['r1']
        records['child'] = dict(id='child', name='子区块', description='', controls={}, tasks={}, actions=r['actions'])
        r['actions'] = {}
        r['tasks']['Policy']['attempts'].append('missing')
    d.publish(run, 'cross', cross)
    records = d.load(run)[1]
    text = tasks().render(records['r1'], records)
    assert '点击后仍为空状态' in text and '动作记录缺失' in text
    ctx = tasks().helper('repair_stages').context(run, {'stage':'action', 'request':q})
    assert '点击后仍为空状态' in str(ctx)
    assert len(ctx['区块']) == 1


def test_done_is_concise_and_unattempted_not_claimed_executed(tmp_path):
    run, q, d = setup(tmp_path)
    d.publish(run, 'attempt', seed)
    r = d.load(run)[1]['r1']
    r['tasks']['Policy'].update(status='done', result_evidence='已打开说明')
    text = tasks().render(r)
    assert '已打开说明' in text and '点击后仍为空状态' not in text
    assert '当前图中尚未执行此任务的动作' in text


def test_unknown_delivery_is_not_reported_as_executed():
    describe = tasks().helper('task_attempt_context').describe
    text = '\n'.join(describe({'attempts':['a1']}, {'r': {'actions': {'a1': {'operation':'input_text'}}}}))
    assert '执行情况未确认' in text and '尚无已登记的观察结果' in text
    assert '已执行' not in text
