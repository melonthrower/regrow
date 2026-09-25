import json
from tests.test_stepwise_region_tasks import tasks
from tests.test_stepwise_resume_route import ROOT


def test_action_manual_modules_and_fields():
    stage=json.loads((ROOT/'遍历prompt/流程/02_动作选择.json').read_text())
    text='\n'.join((ROOT/'遍历prompt'/p).read_text() for p in stage['parts'])
    assert '# 动作选择与执行操作手册' in text
    assert '任务要验证的未知属性' in text
    assert '若历史任务写有' not in text
    for word in ['正例','反例','target','end_x','input_text','none']:
        assert word in text


def test_update_and_recovery_manuals_have_field_guides():
    update=tasks().helper('update_step').build_update_request(ROOT,{'本轮探索任务':{'name':'探索'}},['before.png','after.png'])
    assert '# 结果观察与更新操作手册' in update['system_prompt']
    for word in ['previous_regions','not_visible','working_context','attempt_status','domain','findings']:
        assert word in update['system_prompt']
    recovery=tasks().helper('recovery').build_request(ROOT,{'actions':[]},'app','区域',{},'frame.png')
    assert '# 异常恢复操作手册' in recovery['system_prompt']
    for word in ['正例','反例','resume_exploration','framework_tool','restart_app','end_y']:
        assert word in recovery['system_prompt']
    assert len(recovery['fixed_parts'])>1


def test_recovery_schema_is_unchanged():
    r=tasks().helper('recovery')
    assert set(r.schema()['properties'])=={'exception','decision','action','framework_tool','reason','handoff'}
    r.validate({'exception':'none','decision':'resume_exploration','action':None,'framework_tool':None,'reason':'恢复','handoff':'待定位'})
