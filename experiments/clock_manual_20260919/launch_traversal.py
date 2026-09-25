"""One entry point: local browser, installed apps, saved/new traversal."""
import importlib.util
import json
from pathlib import Path
import sys
import threading
from urllib.request import urlopen
import webbrowser
from app_launcher import ApplicationHub,Device,repository,write
from progress_window import RoundRunner,server

PORT=39595


def main():
    here=Path(__file__).resolve().parent
    base=Path(json.loads((here/'current_source.json').read_text())['source']) if (here/'current_source.json').exists() else here
    runs=base/'luna_runs';url=f'http://127.0.0.1:{PORT}/'
    try:
        with urlopen(url+'health',timeout=2) as response:health=json.load(response)
        if health=={'service':'stepwise_launcher','root':str(runs.resolve())}:
            print(url,flush=True);webbrowser.open_new_tab(url);return
    except (OSError,ValueError):pass
    initial=None;serial=None
    saved=runs/'launcher_current.json'
    if saved.exists():
        last=json.loads(saved.read_text());initial=runs/last['run'];serial=last['device']
    if initial is None:
        manifests=sorted(runs.glob('*/run_manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        if not manifests:raise ValueError('No configured emulator; initialize the experiment device first')
        initial=manifests[0].parent;serial=json.loads(manifests[0].read_text())['device']
    device=Device(serial)
    spec=importlib.util.spec_from_file_location('launcher_mirror',repository()/'tools/android_web_mirror.py')
    mirror_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(mirror_module)
    mirror=mirror_module.make_server(mirror_module.MirrorService(mirror_module.AdbClient(device.adb,serial),1500),'127.0.0.1',0)
    threading.Thread(target=mirror.serve_forever,daemon=True).start()
    hub=ApplicationHub(runs,device,RoundRunner,initial)
    app=server(initial,f'http://127.0.0.1:{mirror.server_port}',PORT,hub=hub)
    write(runs/'launcher_service.json',{'url':url,'device':serial,'entry':str(Path(__file__).resolve()),'mirror_port':mirror.server_port})
    print('遍历窗口：'+url,flush=True)
    threading.Thread(target=lambda:webbrowser.open_new_tab(url),daemon=True).start()
    print('若终端没有图形浏览器，请在客户端打开上面的地址；远程连接需要转发该端口。',flush=True)
    try:app.serve_forever()
    finally:app.server_close();mirror.shutdown();mirror.server_close()


if __name__=='__main__':main()
