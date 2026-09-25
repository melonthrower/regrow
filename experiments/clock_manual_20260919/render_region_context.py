"""Render current committed Region knowledge without an API or GUI call."""
import argparse
import json
from pathlib import Path
import shutil

from stepwise_flow import assemble_current_context


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('region')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    request=assemble_current_context(root,args.run,args.region)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,value in [('request.json',request),('progress.json',request['progress']),
                       ('response.schema.json',request['response_schema'])]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    for name,key in [('dynamic.prompt','dynamic_prompt'),('system.prompt','system_prompt'),('user.prompt','user_prompt')]:
        (args.output/name).write_text(request[key]+'\n')
    for part in request['fixed_parts']:
        path=args.output/'fixed'/part['path'];path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(part['text'])
    if request['image_refs']:
        shutil.copy2(args.run/request['image_refs'][0],args.output/'attached-frame.png')
    for name in ('stepwise_flow.py','render_region_context.py'):
        shutil.copy2(root/name,args.output/name.replace('.py','.snapshot.py'))
    (args.output/'REPORT.md').write_text(
        '# 框架生成的区块上下文\n\n'
        '从 knowledge_current.json 读取已提交区块，未调用模型或执行GUI。'
        '待继续区块不可交互时，从当前落点生成最短已知路径及第一步动作请求；没有可用路径或仍有待处理分支时，仅生成历史。\n\n'
        '[上下文](dynamic.prompt) · [进度](progress.json) · [组装记录](request.json)\n\n'
        '原始模型描述按来源读取；只披露本区及必要来源，内部编号留在后台。\n')
    print(request['dynamic_prompt'])


if __name__=='__main__':main()
