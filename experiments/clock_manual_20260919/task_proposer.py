"""Build task proposals from Region observations, history and shared tasks."""
import json
from pathlib import Path
from register_update import sibling as helper


def proposal_schema():
    value=json.loads((Path(__file__).parent/'遍历prompt/输出格式/区块探索任务.schema').read_text())
    value['properties']['operations']['items']['properties']['findings']={'type':'array','items':json.loads((Path(__file__).parent/'遍历prompt/输出格式/参数发现.schema').read_text())}
    value['properties']['operations']['items']['properties']['prerequisite']=helper('task_prerequisites').schema()
    value['properties']['operations']['items']['properties']['registration_kind']={
        'type':'string','enum':['entry','parameter','control_effect'],
        'description':'探索产物：entry登记入口去向与用途；parameter登记参数事实；control_effect登记试探控件的直接反馈。'}
    value['properties']['operations']['items']['properties']['conditions']={'type':'array','items':{'type':'string','minLength':1},
        'description':'只用于区分同一控件同一动作的不同功能用途，例如文件页与日历页的加号。优先标明影响用途的当前功能页或对象类别，不以运行/停止、按钮此刻可见等状态替代页面条件。这不是操作可执行的前置条件：运行才能暂停属于当前状态或prerequisite，不是另一个暂停用途。稳定用途填[]，已有相同用途逐字复用其条件；未证实影响用途的状态不写入。'}
    value['properties']['operations']['items']['properties']['knowledge']={'type':'string',
        'description':'仅record填写一句稳定用途或规则；不要附加本次显示值、选中状态或选项表。参数写findings，当前状态证据写reason/evidence；其余handling为空。'}
    value['properties']['shared_instances']={'type':'array','items':{
        'type':'object','properties':{k:{'type':'string'} for k in
            ('control','source_region','source_control','reason')},
        'required':['control','source_region','source_control','reason'],'additionalProperties':False}}
    return value


def plan_request(root,records,state,rid):
    normalize=helper('action_commands').normalize
    region=records[rid]
    schema=proposal_schema()
    schema['required'].append('shared_instances')
    sharing=schema['properties']['shared_instances']['items']['properties']
    sharing['source_region'].update(enum=list(records),description='逐字复制可引用同类实例的region身份，例如r0001，不填区块名称。')
    sharing['source_control'].update(enum=sorted({cid for r in records.values() for cid in r.get('controls',{})}),
        description='逐字复制来源实例的control身份，例如c0001，不填控件名称。')
    # Strict API requires every property; local validation still accepts old evidence.
    schema['properties']['operations']['items']['required']+=['findings','prerequisite','registration_kind','knowledge','conditions']
    schema['properties']['operations']['items']['properties']['control']['enum']=[c['name'] for cid,c in region['controls'].items() if not helper('shared_tasks').automatic_tasks(region,cid)]+['']
    visible=set(state.get('observation',{}).get('control_refs',[]))
    dynamic={'区块':region['name'],'描述':region['description'],
        '上步观察交接':helper('target_observation').handoff(records,state),
        '描述来源':'已有区块记录，可能来自更早观察；当前对象与状态以截图为准。图片匹配定位不重新确认语义，登记名中的实例与本图不一致时，不把当前对象的任务绑定给历史实例；用partial说明需重新辨认的控件与归属缺口。',
        '补充清点原因':region.get('task_inventory',{}).get('review',{}).get('reason',''),
        '控件':[{'name':c['name'],'目标观察':helper('target_observation').describe(c,state.get('observation',{}).get('id')),
                 '当前定位':'本轮已定位，仍需看图核对' if cid in visible else '本轮未定位，仅为历史记录',
                 '已有任务':[n for n,t in region.get('tasks',{}).items() if t.get('control')==cid],
                 '已完成任务知识':helper('task_knowledge').control_knowledge(region,cid,records),
                 '已验证入口':helper('entry_evidence').disclose(region,cid,records),
                 '框架已关联共享任务':helper('shared_tasks').automatic_tasks(region,cid),
                 '其他区块的同名入口历史':helper('entry_evidence').related(region,cid,records)} for cid,c in region['controls'].items()],
        '已有任务':region.get('tasks',{}),
        '区块操作知识':helper('task_knowledge').control_knowledge(region,None),
        '可引用同类实例':[{'region':other,'control':cid,'区块':r['name'],'名称':c['name'],
            '说明':c.get('description',''),'功能线索':next((v.get('possible_operation','') for v in reversed(c.get('observations',[])) if not v.get('visual_only')),''),
            '任务':[{'name':n,'action':t.get('action'),'kind':helper('task_settlement').registration_kind(t),
                     'status':t.get('status'),'conditions':t.get('conditions',[]),'knowledge':t.get('knowledge','')}
                    for n,t in r.get('tasks',{}).items() if t.get('control')==cid and not t.get('shared_task_ref')]}
            for other,r in records.items() for cid,c in r.get('controls',{}).items()
            if other==rid or any(t.get('control')==cid and not t.get('shared_task_ref') for t in r.get('tasks',{}).values())],
        '其他区块（仅历史名称索引，不表示本图可见，不在本轮清点范围）':[{'名称':r['name']} for other,r in records.items() if other!=rid],
        '说明':'只清点本区块，control逐字使用给定控件名称；其他区块入口不影响本区块清点。本区块内仍有未辨认或未登记入口时用partial，仅说明缺口，不为未知入口编造任务。入口及任务已列齐就用complete；尚未执行的explore任务不影响清点完整性，完成进度由框架另算。空任务不自动表示清点完成。'}
    inventory=region.get('task_inventory',{})
    if region.get('registration_gaps',{}).get('discovery',{}).get('pending'):
        dynamic['发现中尚未确认的事项']=region['registration_gaps']['discovery']['pending']
        dynamic['发现缺口说明']='未知对象不进入确认地图；已有可信任务可先执行，清点完整性不因已登记子集覆盖就获得确认。位置属于原观察，换帧需按当前图核对。'
    if inventory.get('inventory') in ('partial','uncertain'):
        dynamic['上次清点缺口']={key:inventory.get(key) for key in ('inventory','evidence','source_call')}
        dynamic['上次清点缺口']['说明']='这是历史缺口，需按当前截图和已有观察重新核对；滚动任务结束不自动证明缺口已解决。'
    # Backend control IDs are absent from the model's task catalog.
    dynamic['已有任务']=[{'name':n,'control':region['controls'][t['control']]['name'] if t['control'] else region['name'],
                         '知识来源':'历史共享任务，不是本地执行或当前状态' if t.get('shared_task_ref') else '本区块任务',
                         'handling':t['handling'],'status':t['status'],'reason':t['reason'],'action':normalize(t)['action'],'task_type':t['task_type'],
                         'registration_kind':helper('task_settlement').registration_kind(t),'conditions':t.get('conditions',[]),
                         '已登记前置条件':t.get('prerequisite'),
                         '暂挂原因':t.get('deferral',{}).get('reason') or t.get('blocker',{}).get('reason',''),
                         '恢复条件':t.get('deferral',{}).get('retry_when','需显式复核；仅重新定位不解除' if t.get('blocker',{}).get('condition')=='review_required' else '')}
                        for n,t in region.get('tasks',{}).items()]
    # One ordered source for both the sent prompt and its per-file audit trail.
    paths=(
        '共享/任务知识与当前观察.prompt',
        '任务/区块探索任务.prompt',
        '任务/探索范围与退出.prompt',
        '任务/任务粒度与反馈.prompt',
        '任务/历史入口与共享复用.prompt',
        '任务/任务登记与补全.prompt',
        '任务/输入与搜索探索正反例.prompt',
        '共享/参数观察值.prompt',
        '共享/任务结束条件.prompt',
        '任务/参数关系调查.prompt',
        '任务/前置条件与恢复.prompt',
    )
    parts=[{'path':path,'text':(Path(root)/'遍历prompt'/path).read_text()} for path in paths]
    request={'pipeline_step':'discovery','stage':'task_proposal','role':'task_proposal','action_ready':False,
        'system_prompt':'\n\n'.join(part['text'] for part in parts),'user_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'dynamic_prompt':json.dumps(dynamic,ensure_ascii=False,indent=2),
        'screenshots':[state['observation']['image']],'image_refs':[state['observation']['image']],
        'response_schema':schema,'fixed_parts':parts,
        'source':{'region':rid,'observation':state['observation']['id']}}
    helper('page_history').attach(request,records,state)
    return helper('parameter_evidence_review').augment(request,region)



class TaskProposer:
    @staticmethod
    def request(root, records, state, region, *, scope_review=False):
        return (helper('traversal_scope').review_request(root, records, state, region) if scope_review
                else plan_request(root, records, state, region))

    @staticmethod
    def run(repair, request):
        # Runner owns the unchanged schema, corrections, commit_plan and publication.
        return repair.perform('task_proposal', request)
