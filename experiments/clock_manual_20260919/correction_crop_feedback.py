"""Show rejected identity bounds as derived evidence, never as a new observation."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw


def attach(run, job, request):
    indices=job.get('identity_controls',[])
    if job.get('stage')!='update' or not job.get('attempt') or not indices:return
    run=Path(run)
    source=run/'action_attempts'/job['attempt']/'after.png'
    originals=[(run/p).resolve() for p in job['request'].get('screenshots',[])]
    if source.resolve() not in originals:raise ValueError('裁图必须来自原请求中的真实动作后图')
    frame=Image.open(source).convert('RGB');width,height=frame.size
    fingerprint=hashlib.sha256(source.read_bytes()+json.dumps(job['candidate'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    folder=run/Path(job['path']).parent/'identity_crop_feedback'/fingerprint
    folder.mkdir(parents=True,exist_ok=True)
    rows=[];panels=[]
    for index in indices:
        control=job['candidate']['controls'][index];box=control.get('bbox')
        row={'index':index,'name':control.get('name'),'bbox':box}
        rows.append(row)
        if not isinstance(box,dict) or any(type(box.get(k)) is not int for k in ('left','top','right','bottom')):
            row['unavailable']='没有有效整数身份框';continue
        left,top,right,bottom=(box[k] for k in ('left','top','right','bottom'))
        if not (0<=left<right<=width and 0<=top<bottom<=height):
            row['unavailable']='身份框越界或为空，未生成伪造补边';continue
        crop=frame.crop((left,top,right,bottom));path=folder/f'control-{index}.png';crop.save(path)
        row['crop']=str(path.relative_to(run));row['size']=list(crop.size)
        context=(max(0,left-48),max(0,top-48),min(width,right+48),min(height,bottom+48))
        surrounding=frame.crop(context);draw=ImageDraw.Draw(surrounding)
        draw.rectangle((left-context[0],top-context[1],right-context[0]-1,bottom-context[1]-1),outline='red',width=3)
        panel=Image.new('RGB',(960,300),'white');d=ImageDraw.Draw(panel)
        d.text((8,8),f'controls[{index}] bbox=({left},{top},{right},{bottom}) original={width}x{height}',fill='black')
        d.text((8,30),'LEFT: exact crop    RIGHT: context, red = rejected bbox (not a suggested fix)',fill='black')
        for x,img in [(8,crop.copy()),(490,surrounding)]:
            img.thumbnail((460,240));panel.paste(img,(x,54))
        panels.append(panel)
    meta={'source':str(source.resolve()),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'candidate_sha256':hashlib.sha256(json.dumps(job['candidate'],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
          'original_size':[width,height],'controls':rows}
    if panels:
        sheet=Image.new('RGB',(960,300*len(panels)),'white')
        for i,panel in enumerate(panels):sheet.paste(panel,(0,300*i))
        path=folder/'contact.png';sheet.save(path)
        request['screenshots']=list(request.get('screenshots',[]))+[str(path.resolve())]
        request['image_refs']=list(request['screenshots']);meta['image_number']=len(request['screenshots'])
    (folder/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    request['identity_crop_evidence']=meta
    text='\n\n身份框派生核对证据（不是新观察）：'+json.dumps(meta,ensure_ascii=False)
    if panels:
        text+='\n最后追加图的左列是被拒绝身份框实际裁图，右列是同一原动作后图的周边参照；红框仅表示旧框，不是正确答案。拼图经过缩放，严禁将拼图坐标当原图坐标。'
    else:
        text+='\n所选身份框均无法生成裁图，没有追加图片；请依据原图核对，不将原图解释为拼图。'
    text+='输出仍使用原整屏像素；核对文字是否被切断及是否有遮挡，不确定时如实保留uncertain或空框，不得声称完整清晰。原图和原任务仍有效。'
    request['user_prompt']+=text;request['dynamic_prompt']=request['user_prompt']
