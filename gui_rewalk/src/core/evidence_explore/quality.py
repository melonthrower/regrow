"""Read-only model audit and concrete geometry feedback; never invents executable fixes."""
from .protocol import obj,T
from .records import valid_box,inside

REVIEW_SCHEMA=obj(dict(inventory_required={'type':'boolean'},visible_complete={'type':'boolean'},
    missing={'type':'array','items':T,'maxItems':32},misidentified={'type':'array','items':T,'maxItems':32},
    unexpected_changes={'type':'array','items':T,'maxItems':16}))
REVIEW_PROMPT='''你是GUI登记审核者，只输出一份最终JSON。独立逐区观察当前截图，不因为清单里已经写了就默认正确。图片如有两张，第一张是比较/动作前，最后一张是当前。
判断当前输入层是否已经到达goal要求清点的功能表面：已到达则inventory_required=true；任务范围外的准备导航可false，不要求清点无关主窗口。若required=true，检查所有当前可见独立设置/操作，包括禁用项、数值框、滑条、开关、列表能力和底部按钮。静态标题不是控件；未展开或未滚动的隐藏项不算当前漏项。共享导航/底栏已明确由提供的登记覆盖时无需重复清点。
missing写当前可见但清单缺少的具体项目，misidentified写错误功能/状态/位置、语义重复或框与标签错配。不输出坐标补丁，不执行动作，不从软件常识补出不可见项。visible_complete仅描述本视口，不表示整个应用完成。看不清也要写明，不用自信语气掩盖歧义。
如果pending_action.kind为scroll，比较两图及动作前登记，重点检查值、勾选、选中项是否意外改变。仅平移/新出现/消失不是值改变；只写有证据的具体变化到unexpected_changes。不因上一模型说成功就忽略副作用；没证据时返回空列表。其他动作的expected导航变化不要当滚动副作用。'''


def geometry_feedback(raw,error):
    surface=raw.get('surface_box');bad=[]
    for i,c in enumerate(raw.get('controls',[])):
        b=c.get('box');context=c.get('context_box',b)
        try:
            ok=valid_box(b) and valid_box(context) and valid_box(surface)
            ok=ok and inside(b[:2],context) and inside(b[2:],context) and inside(context[:2],surface) and inside(context[2:],surface)
        except (TypeError,IndexError):ok=False
        if not ok:bad.append(dict(index=i,**{k:c.get(k) for k in ['key','label','box','context_box']}))
    return dict(error=error,surface_box=surface,controls=bad,
        constraints='0<=surface.left<=context.left<=box.left<box.right<=context.right<=surface.right<=1000; same for top/bottom.',
        instruction='根据当前图只纠正真实错误框。不得为迎合框而任意扩大前景；若目标属于背景，移除它并安全恢复。保留其它正确登记。')


def valid_review(raw):
    return (isinstance(raw,dict) and set(raw)==set(REVIEW_SCHEMA['properties'])
        and type(raw['inventory_required']) is bool and type(raw['visible_complete']) is bool
        and all(isinstance(raw[k],list) and len(raw[k])<=REVIEW_SCHEMA['properties'][k]['maxItems'] and all(isinstance(v,str) for v in raw[k])
            for k in ['missing','misidentified','unexpected_changes']))
