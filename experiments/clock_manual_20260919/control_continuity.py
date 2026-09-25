"""A local update identity question, not an automatic split or migration."""

def diagnostic(control, proposal):
    previous=(control.get('observations') or [{}])[-1]
    a,b=previous.get('bbox'),proposal.get('bbox')
    separated=bool(a and b and (a['right']<=b['left'] or b['right']<=a['left'] or
                               a['bottom']<=b['top'] or b['bottom']<=a['top']))
    changed=(proposal.get('name') or proposal.get('text'))!=control['name']
    if changed and separated and not proposal.get('identity_evidence','').strip():
        return {'previous_name':control['name'],'previous_box':a,'candidate_box':b,
                'source':previous.get('evidence'),
                'question':'名称及位置变化只触发核对：旧对象是否仍独立存在？若是新出现对象则不继承；同一对象状态或布局变化需填写identity_evidence说明前后对应；不确定时不覆盖旧身份，将待核对内容记入uncertainties。'}
    return None


def extend_schema(schema):
    control=schema['properties']['controls']['items']
    control['properties']['identity_evidence']={'type':'string','description':'继承旧控件时的前后对象对应依据；没有疑点可为空。由旧控件触发的新对象不能继承其身份。'}
    control['required']=list(dict.fromkeys(control['required']+['identity_evidence']))
