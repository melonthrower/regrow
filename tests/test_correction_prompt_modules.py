from tests.test_recovery_discovery import mod, ROOT


def test_binding_repair_does_not_load_registration_and_parse_instructions():
    job={'stage':'action','blocked_by':'binding_conflict','request':{},'error':'target unavailable'}
    names=mod('correction_prompts').select(job,{})
    assert '定位绑定' in names
    assert '任务归属' not in names and '回复解析' not in names and '结果证据' not in names


def test_all_structured_diagnostics_select_their_modules():
    job={'stage':'update','request':{},'error':{'errors':[{'code':'duplicate_binding'},{'code':'control_owner_surface'}]}}
    names=mod('correction_prompts').select(job,{})
    assert {'登记修订','区块归属','结果证据'}<=set(names)


def test_parse_failure_is_not_a_record_error():
    job={'stage':'task_proposal','request':{},'parse_failure':{'reason':'incomplete'},'blocked_by':'model_response_parse_error'}
    names=mod('correction_prompts').select(job,{})
    assert names==['回复解析']


def test_unknown_diagnostic_keeps_general_record_guidance():
    names=mod('correction_prompts').select({'stage':'task_proposal','request':{},'error':'older untyped error'}, {})
    assert '登记修订' in names and '任务归属' in names


def test_old_parse_failure_does_not_hide_later_semantic_rejection():
    job={'stage':'update','request':{},'blocked_by':'model_response_parse_error','parse_failure':{'reason':'old truncation'},
         'candidate':{'action_result':{}},'error':'current source and destination disagree'}
    names=mod('correction_prompts').select(job,{})
    assert '回复解析' not in names
    assert {'结果证据','登记修订','区块归属'}<=set(names)


def parse_request(candidate):
    import json
    job={'stage':'function_registration','request':{'system_prompt':'登记功能','user_prompt':'本轮任务',
        'response_schema':{'type':'object'},'screenshots':[]},'history':[],
        'blocked_by':'model_response_parse_error','candidate':candidate,
        'parse_failure':{'call':'old-call','reason':'incomplete_reply','reply_texts':['{"broken":']},
        'error':'当前候选中的控件名不匹配' if candidate is not None else '模型回复解析错误：incomplete_reply'}
    request=mod('step_repair').request(ROOT,job,{})
    return job,json.loads(request['user_prompt']),request


def test_generated_context_distinguishes_old_parse_failure_from_current_rejection():
    job,context,request=parse_request({'control':'wrong name'})
    assert context['框架错误分类']=='review_required'
    assert '当前模型回复解析错误' not in context
    assert '历史模型回复解析错误' not in context
    assert job['parse_failure']['reply_texts']==['{"broken":']
    assert 'broken' not in request['user_prompt']
    assert '已解析' in context['当前候选解析状态']
    assert '模型回复解析错误' not in context
    assert job['blocked_by']=='model_response_parse_error'  # audit is not rewritten
    assert '纠错/回复解析.prompt' not in [p['path'] for p in request['fixed_parts']]


def test_generated_context_preserves_real_current_parse_failure():
    job,context,request=parse_request(None)
    assert context['框架错误分类']=='model_response_parse_error'
    assert context['当前模型回复解析错误']==job['parse_failure']
    assert '历史模型回复解析错误' not in context
    assert '纠错/回复解析.prompt' in [p['path'] for p in request['fixed_parts']]


def test_parse_audit_is_retained_even_without_a_current_candidate():
    detail={'call':'old','reason':'incomplete_reply'}
    context=mod('correction_prompts').parse_disclosure({'blocked_by':'review_required','parse_failure':detail})
    assert '当前模型回复解析错误' not in context
    assert '历史模型回复解析错误' not in context
    assert detail=={'call':'old','reason':'incomplete_reply'}
    assert context['框架错误分类']=='review_required'
