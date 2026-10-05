"""Associate an action proposal with recorded visual candidates, before delivery."""


def bind_action_target(request, proposal):
    binding=_bind_action_target(request,proposal)
    source=request.get('source',{})
    if binding.get('status')=='matched' and request.get('preparation_allowed') and source.get('task_type')=='single_action':
        expected={'tap':'click'}.get(source.get('task_action'),source.get('task_action'))
        action={'tap':'click'}.get(proposal.get('action'),proposal.get('action'))
        binding['preparatory_action']=(binding.get('control_ref')!=source.get('task_control') or action!=expected)
    return binding



def _bind_action_target(request, proposal):
    """Conservative linkage to recorded candidates, not a live identity verifier.

    Never guess nearest controls or enlarge text boxes into unknown row bounds.
    Low-confidence image evidence is advisory when it agrees with the model position.
    """
    base = {'region_ref':request['source']['region'],
            'observation_ref':request['source']['observation'], 'control_ref':None,
            'working_region':request['source'].get('working_region',request['source']['region'])}
    for key in ('task_name','task_region','task_type','return_to'):
        if key in request['source']:base[key]=request['source'][key]
    if proposal.get('action') == 'back':
        if proposal.get('x') is None and proposal.get('y') is None:
            return {**base,'status':'matched','basis':'region-owned return action; verify foreground before delivery'}
        return {**base,'status':'unresolved','reason':'back not allowed for this task'}
    if proposal.get('action') in ('key_press','hotkey'):
        return {**base,'status':'matched','basis':'Region-owned keyboard action; current focus must be observed'}
    if proposal.get('action') == 'wait':
        return {**base,'status':'matched','basis':'Region-owned observation wait'}
    if proposal.get('action') == 'none':
        return {**base, 'status':'no_action'}
    if proposal.get('action')=='scroll':
        import region_scroll
        return region_scroll.bind(request,proposal,base)
    if proposal.get('action') in ('hover','drag'):
        from PIL import Image
        from pathlib import Path
        frames=request.get('image_refs',[])
        if len(frames)!=1 or not Path(frames[0]).is_file():
            return {**base,'status':'unresolved','reason':'current screenshot is missing'}
        coords=[proposal.get(k) for k in ('x','y','end_x','end_y')]
        if proposal.get('action')=='hover':coords=coords[:2]+coords[:2]
        if any(type(v) is not int for v in coords):
            return {**base,'status':'unresolved','reason':'scroll needs integer start and end coordinates'}
        with Image.open(frames[0]) as frame:width,height=frame.size
        x,y,ex,ey=coords
        if not (0<=x<width and 0<=y<height and (0<=ex<width and 0<=ey<height)) or ((x,y)==(ex,ey) and proposal.get('action')!='hover'):
            return {**base,'status':'unresolved','reason':'pointer coordinates outside screenshot or no displacement'}
        # Hover and drag still need the same target association as a click.
    if proposal.get('action')=='input_text' and (not (request.get('allow_input') or request.get('navigation_advice')) or not isinstance(proposal.get('text'),str)):
        return {**base,'status':'unresolved','reason':'input is outside the routed task'}
    if proposal.get('action') not in ('tap','click','double_click','long_press','right_click','input_text','hover','drag'):
        return {**base, 'status':'unresolved', 'reason':'unsupported operation'}
    x, y = proposal.get('x'), proposal.get('y')
    if any(isinstance(v, bool) or not isinstance(v, (int,float)) for v in (x,y)):
        return {**base, 'status':'unresolved', 'reason':'missing position'}
    target = str(proposal.get('target','')).strip().casefold()
    from pathlib import Path
    import importlib.util
    spec=importlib.util.spec_from_file_location('stepwise_image_match',Path(__file__).with_name('visual_choices.py'))
    matcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(matcher)
    frames=request.get('image_refs',[])
    if len(frames)!=1 or not Path(frames[0]).is_file():
        return {**base,'status':'unresolved','reason':'current screenshot is missing'}
    from PIL import Image
    with Image.open(frames[0]) as frame:width,height=frame.size
    if not (0<=x<width and 0<=y<height):return {**base,'status':'unresolved','reason':'coordinates outside screenshot'}
    hits=[];selected={};model_grounded=set();diagnostics=[];matches={};competing=[]
    current_matches=matcher.match_controls(request['backend_candidates'],frames[0])
    named=[c for c in request['backend_candidates'] if target and target in
           [str(c.get(k,'')).strip().casefold() for k in ('name','icon_description')]]
    point_binding=bool(target) and not named and proposal.get('action') in ('tap','click','double_click','long_press','right_click','hover','drag','input_text')
    for c in (request['backend_candidates'] if point_binding else named):
        if not c.get('image') or not Path(c['image']).is_file():
            diagnostics.append(c['name']+'：缺少记录图片');continue
        match=current_matches[c['id']]
        matches[c['id']]=match
        diagnostics.append(c['name']+'：候选范围'+str(match.get('box'))+'，模型位置'+str((x,y))+'，图片判断'+str(match.get('reason',match.get('accepted'))))
        if not match['accepted']:
            if point_binding:
                # An admitted alternative at this point prevents certainty about another object.
                # It does not make this weaker object the correct target.
                if any(v['box'][0]<=x<v['box'][2] and v['box'][1]<=y<v['box'][3]
                       for v in match.get('candidates',[]) if v.get('box')):
                    competing.append(c)
                continue
            disclosed=request.get('visual_choices',{}).get(c['id'],[])
            alternatives=[v for v in match.get('candidates',[]) if any(v['box']==d['box'] for d in disclosed)
                          and v['box'][0]<=x<v['box'][2] and v['box'][1]<=y<v['box'][3]]
            if len(alternatives)==1 and str(proposal.get('reason','')).strip():
                hits.append(c);selected[c['id']]=alternatives[0]
            elif not match.get('candidates') and match.get('box') and str(proposal.get('reason','')).strip():
                left,top,right,bottom=match['box']
                if left<=x<right and top<=y<bottom:
                    hits.append(c);model_grounded.add(c['id'])
            continue
        left,top,right,bottom=match['box']
        if left<=x<right and top<=y<bottom:hits.append(c)
    if len(hits)==1:
        if not point_binding and not matches[hits[0]['id']]['accepted']:
            # Renaming a weak proposal cannot resolve a different strong object at its point.
            for other in request['backend_candidates']:
                if other['id']==hits[0]['id'] or not other.get('image') or not Path(other['image']).is_file():continue
                match=current_matches[other['id']]
                if match.get('accepted') and match.get('box'):
                    left,top,right,bottom=match['box']
                    if left<=x<right and top<=y<bottom:
                        return {**base,'status':'unresolved',
                                'reason':'目标 '+hits[0]['name']+' 只有弱图片依据，而同一点另有强匹配对象 '+other['name']+
                                '。改写目标名称或重复声明可见不能解除此跨对象歧义；请补充观察，或依据当前图选择必要准备动作，无法核实时保留缺口。'}
        if point_binding and competing:
            names='、'.join(c['name'] for c in hits+competing)
            return {**base,'status':'unresolved',
                    'reason':'点位同时有不同登记对象的当前图片候选：'+names+
                    '。其他对象匹配较弱不证明唯一强匹配就是实际操作对象。请按单张当前图核对对象，'
                    '改用弱对象名称不能解除它与强对象的同点竞争；可补观察或选择有当前依据的必要准备动作，不能确认则保留缺口。'}
        base['region_ref']=hits[0].get('region_ref',base['region_ref'])
        layout=matches[hits[0]['id']].get('layout_evidence')
        if layout:
            return {**base,'status':'matched','control_ref':hits[0]['id'],'layout_evidence':layout,
                    'basis':'current group pixels and relative positions match the recorded controls; functional meaning is not independently verified'}
        if hits[0]['id'] in model_grounded:
            return {**base,'status':'matched','control_ref':hits[0]['id'],'model_grounded':True,
                    'basis':'model position agrees with low-confidence image candidate; no visual contradiction established'}
        if hits[0]['id'] in selected:
            return {**base,'status':'matched','control_ref':hits[0]['id'],'visual_choice':selected[hits[0]['id']],
                    'basis':'model selected one disclosed appearance candidate; current image reconfirmed its bounds'}
        return {**base,'status':'matched','control_ref':hits[0]['id'],
                'basis':'unique strong visual match at model point; target wording differed' if point_binding else 'exact description and unique crop match in supplied frame; live check still required'}
    reason=('当前候选表没有目标 '+str(proposal.get('target')) if not diagnostics else '多个登记对象同时符合，需区分身份' if len(hits)>1 else '目标未能对应：'+'；'.join(diagnostics))
    if not target:return {**base,'status':'unresolved','reason':'missing target description'}
    return {**base,'status':'matched','model_grounded':True,
            'basis':'execute model coordinates; recorded control association remains unconfirmed',
            'association':{'status':'unconfirmed','target':proposal['target'],'x':x,'y':y,
                           'candidates':[{'region':c.get('region_ref',base['region_ref']),'control':c['id'],
                               'position':selected.get(c['id'],matches.get(c['id'],{})).get('box'),
                               'basis':'current visual candidate at model point' if c in hits else 'target wording candidate; not visually confirmed'} for c in (hits or named)],
                           'reason':reason}}
