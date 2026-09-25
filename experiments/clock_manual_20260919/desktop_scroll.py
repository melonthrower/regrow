"""OSWorld wheel units: positive dy up, positive dx right; no swipe endpoints."""
from pathlib import Path
from PIL import Image


def extend_schema(node):
    if isinstance(node, dict):
        props = node.get('properties', {})
        if all(k in props for k in ('action', 'x', 'y', 'end_x', 'end_y')):
            for key in ('dx', 'dy'):
                props[key] = {'type':['integer','null']}
                if key not in node.setdefault('required', []):node['required'].append(key)
        for child in node.values():extend_schema(child)
    elif isinstance(node, list):
        for child in node:extend_schema(child)


def validate(p):
    if any(type(p.get(k)) is not int for k in ('x','y','dx','dy')):
        raise ValueError('Desktop scroll needs integer x/y and wheel dx/dy')
    if min(p['x'],p['y']) < 0 or not (p['dx'] or p['dy']):
        raise ValueError('Desktop scroll needs a valid origin and nonzero wheel amount')
    if any(p.get(k) is not None for k in ('end_x','end_y')):
        raise ValueError('Desktop scroll uses dx/dy, not swipe endpoints')


def commands(p):
    validate(p)
    move=f"pyautogui.moveTo({p['x']},{p['y']})"
    return [move+f"; pyautogui.{method}({p[key]})" for key,method in (('dx','hscroll'),('dy','vscroll')) if p[key]]


def bind(request,p):
    try:validate(p)
    except ValueError as e:return {'status':'unresolved','reason':str(e)}
    frames=request.get('image_refs',[])
    if len(frames)!=1 or not Path(frames[0]).is_file():return {'status':'unresolved','reason':'current screenshot missing'}
    with Image.open(frames[0]) as image:width,height=image.size
    x,y=p['x'],p['y']
    if not (0<=x<width and 0<=y<height):return {'status':'unresolved','reason':'wheel origin outside screenshot'}
    if request.get('navigation_advice'):
        return {'status':'matched','model_grounded':True,'basis':'navigation wheel origin in current screenshot'}
    if not request.get('allow_scroll'):return {'status':'unresolved','reason':'scroll outside routed task'}
    import identity_templates as templates
    import image_match
    template=request.get('region_image')
    if not templates.usable({'image':template,**request.get('region_image_assessment',{})}):
        return {'status':'unresolved','reason':'Region identity template missing or not admitted'}
    match=image_match.locate(template,frames[0])
    if not match['accepted']:return {'status':'unresolved','reason':'scroll Region not localized'}
    left,top,right,bottom=match['box']
    if not(left<=x<right and top<=y<bottom):return {'status':'unresolved','reason':'wheel origin outside Region'}
    return {'status':'matched','basis':'OSWorld wheel origin lies in matched Region'}
