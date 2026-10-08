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
    """Explicit linkage to recorded candidates, not a live identity verifier.
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
    from pathlib import Path
    from PIL import Image
    frames=request.get('image_refs',[])
    if len(frames)!=1 or not Path(frames[0]).is_file():
        return {**base,'status':'unresolved','reason':'current screenshot is missing'}
    with Image.open(frames[0]) as frame:width,height=frame.size
    if not (0<=x<width and 0<=y<height):
        return {**base,'status':'unresolved','reason':'coordinates outside screenshot'}
    target=str(proposal.get('target','')).strip()
    candidates=request.get('backend_candidates',[])
    # Identity is the model's explicit choice. Geometry is execution input, not
    # evidence that a different recorded control owns this action.
    hits=[c for c in candidates if target==candidate_key(request,c)]
    if not hits:
        hits=[c for c in candidates if target.casefold() in
              [str(c.get(k,'')).strip().casefold() for k in ('name','icon_description')] and target]
    if len(hits)==1:
        c=hits[0]
        return {**base,'region_ref':c.get('region_ref',base['region_ref']),
                'status':'matched','control_ref':c['id'],'model_grounded':True,
                'basis':'explicit recorded control selection; coordinates do not verify identity or outcome'}
    if len(hits)>1:
        return {**base,'status':'unresolved','reason':'同名控件不唯一，请用候选中的 region/control 身份填写 target'}
    if not target:return {**base,'status':'unresolved','reason':'missing target description'}
    return {**base,'status':'matched','model_grounded':True,
            'basis':'unrecorded model target; no recorded identity inferred from coordinates',
            'association':{'status':'unconfirmed','target':target,'x':x,'y':y,
                           'candidates':[],'reason':'target not in the supplied identity candidates'}}


def candidate_key(request,candidate):
    return candidate.get('region_ref',request['source']['region'])+'/'+candidate['id']


def disclose_candidates(request):
    """One bounded catalog from the already admitted action candidates."""
    if not request.get('action_ready'):return request
    import json
    rows=[{'target':candidate_key(request,c),'name':c['name'],
           'region':c.get('region_name',c.get('region_ref',request['source']['region']))}
          for c in request.get('backend_candidates',[])]
    marker='\n\n可登记动作身份（选已有控件时 target 使用下列身份；坐标按当前图选择）：\n'
    old=request.get('_action_identity_text')
    new=json.dumps(rows,ensure_ascii=False)
    for key in ('user_prompt','dynamic_prompt'):
        text=request.get(key,request.get('user_prompt',''))
        request[key]=text.replace(marker+old,marker+new,1) if old and marker+old in text else text+marker+new
    request['_action_identity_text']=new
    return request
