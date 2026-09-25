"""One VLM inventory over a composite, separate from live-frame observations."""
import json
from .protocol import obj,T,BOX
SCHEMA=obj(dict(controls={'type':'array','maxItems':64,'items':obj(dict(key=T,label=T,function=T,box_1000=BOX))},
                uncertain={'type':'array','items':T}))
PROMPT='''这是一块可滚动列表的像素全景，不是当前屏幕。请一次识别图中所有可点击入口，给出原文label、简短function和唯一语义key。纯分组标题不是控件，不把整组多个入口合成一个控件。box_1000以整张图宽高归一化到0..1000，框住对应入口的可点击区域；不要使用原屏幕坐标或推断未见内容。只在final_answer输出一次JSON，不输出中间稿，不执行GUI。看不清或不确定的内容写uncertain。'''


def recognize(panorama,agent):
    if panorama.controls:raise ValueError('catalog already registered')
    height,width=panorama.image.shape[:2]
    if height>2400:raise ValueError('panorama requires tiled perception; not supported in this prototype')
    reply=agent._call(role='region_panorama_inventory',system_prompt=PROMPT,
        user_prompt=f'本区块全景图尺寸：{width}×{height}像素。只识别此图中的入口。',
        screenshots=[(panorama.directory/'panorama.png').read_bytes()],response_schema=SCHEMA)
    panorama.directory.joinpath('model_reply.json').write_text(json.dumps(reply,ensure_ascii=False,indent=2)+'\n')
    controls=[]
    for c in reply['controls']:
        box=c['box_1000']
        if not all(isinstance(v,int) and 0<=v<=1000 for v in box):raise ValueError('invalid normalized box')
        controls.append(dict(key=c['key'],label=c['label'],function=c['function'],
            box=[round(box[0]*width/1000),round(box[1]*height/1000),round(box[2]*width/1000),round(box[3]*height/1000)]))
    panorama.register(controls)
    return reply
