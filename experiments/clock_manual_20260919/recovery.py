"""One recovery policy; action payload is shared with ordinary exploration."""
import importlib.util
from copy import deepcopy
import json
from pathlib import Path
import jsonschema


def helper(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

EXCEPTIONS=['none','blocking_popup','system_error','unexpected_exit','external_app','unclassified']


def schema():
    return {'type':'object','properties':{
        'exception':{'type':'string','enum':EXCEPTIONS},
        'decision':{'type':'string','enum':['act','resume_exploration','stop']},
        'action':{'anyOf':[helper('action_commands').schema(),{'type':'null'}]},
        'framework_tool':{'type':['string','null'],'enum':[None,'restart_app']},
        'reason':{'type':'string'},'handoff':{'type':'string'}},
        'required':['exception','decision','action','framework_tool','reason','handoff'],'additionalProperties':False}


def action_defaults(reply,platform="android"):
    # Match action_commands.validate's defaults when reading an older local reply.
    result=deepcopy(reply)
    if isinstance(result.get('action'),dict):
        defaults={'dx':None,'dy':None} if platform=='desktop' else {}
        result['action']={'skip_task':False,'request_task_review':False,**defaults,**result['action']}
    return result


def validate(reply,platform="android"):
    reply=action_defaults(reply,platform)
    jsonschema.validate(reply,helper('action_commands').platform_request({'response_schema':schema()},platform)['response_schema'])
    action,tool=reply['action'],reply['framework_tool']
    if action:helper('action_commands').validate(action,platform)
    if reply['decision']=='act':
        if bool(action)==bool(tool):raise ValueError('choose one action or framework tool')
        if action and action['action']=='none':raise ValueError('act requires an actual action')
        if tool and reply['exception'] not in ('external_app','unexpected_exit'):raise ValueError('restart not appropriate for this exception')
    elif action or tool:raise ValueError('flow decision must not carry an action')
    if reply['decision']=='resume_exploration' and reply['exception'] not in ('none','blocking_popup'):
        raise ValueError('cannot resume outside the target app or with unclassified obstruction')


def resolve(reply,platform="android"):
    """A cleared exception ends recovery; normal app navigation is not recovery."""
    reply=action_defaults(reply,platform)
    jsonschema.validate(reply,helper('action_commands').platform_request({'response_schema':schema()},platform)['response_schema'])
    result=dict(reply)
    if result['exception']=='none':
        result.update(decision='resume_exploration',action=None,framework_tool=None,
            handoff=reply['handoff']+'\n框架交接：当前异常已消失；原探索任务仍待发现步定位和登记，未执行建议中的后续动作。')
    validate(result,platform)
    return result


def interrupted_tasks(records,state):
    """Recover task ownership from the triggering attempt after active_task clears."""
    attempt=state.get('attempt')
    if not attempt:return []
    return [{'区块':region['name'],'任务':name,
             '任务依据与范围':task.get('reason',''),'处理方式':task.get('handling'),
             '状态':task.get('status'),'结果依据':task.get('result_evidence',''),
             '触发动作':attempt}
            for region in records.values() for name,task in region.get('tasks',{}).items()
            if attempt in task.get('attempts',[])]


def build_request(root,episode,app,region_name,trigger_result,screenshot):
    paths=['异常处理/恢复当前探索.prompt','异常处理/异常识别.prompt','异常处理/恢复策略.prompt',
           '动作/动作空间与字段.prompt','异常处理/恢复输出.prompt']
    parts=[{'path':p,'text':(Path(root)/'遍历prompt'/p).read_text()} for p in paths]
    text='\n\n'.join(p['text'] for p in parts)
    dynamic={'目标应用':app,'平台':'Android触屏，不支持hover','中断的工作区块':region_name,
        '触发异常的结果':trigger_result,'系统恢复边界':'系统异常可用共享GUI动作恢复；没有设备重启工具。反复无效则stop暂停此设备，不修改业务任务或框架代码','异常交接':episode.get('handoff',''),
        '重启工具状态':'本次已使用；不要再次请求，结合截图和启动回执选择其他恢复动作' if any(a.get('framework_tool')=='restart_app' for a in episode['actions']) else '尚未使用；仅目标应用退出或应用外时可请求',
        '框架反馈':episode.get('framework_feedback',''),
        '本次恢复历史':episode['actions'],'要求':'根据最新截图核验上一步效果；交接只是上下文，不能替换固定规则。'}
    if episode.get('interrupted_tasks'):
        dynamic['中断任务（原记录，不代表新增授权）']=deepcopy(episode['interrupted_tasks'])
    return {'role':'recovery','stage':'recovery_action','system_prompt':text,'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'screenshots':[screenshot],'response_schema':schema(),'fixed_parts':parts}


def restart_commands(package,component):
    if not component or not component.startswith(package+'/'):raise ValueError('invalid restart component')
    return [['shell','am','force-stop',package],['shell','am','start','-W','-n',component]]
