"""Bundle existing presentation assets unchanged into three standalone HTML files.
Usage: python build_offline.py FULL_SITE_DIST OUTPUT_DIRECTORY
The source-only export intentionally excludes screenshots: use the authorized full site.
"""
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import sys


def bundle(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or source in output.parents:
        raise ValueError('Output must be separate from source')
    output.mkdir(parents=True, exist_ok=True)
    names = {'slides.html': 'regrow-slides-offline.html',
             'index.html': 'regrow-film-offline.html',
             'progress.html': 'regrow-progress-offline.html'}
    outputs = [output / n for n in names.values()] + [output / 'manifest.json']
    if any(p.exists() for p in outputs):
        raise FileExistsError('Use a new output directory; previous exports are preserved')
    assets = {}
    provenance = {}
    for folder in ['assets', 'film/assets']:
        for path in sorted((source / folder).glob('*.png')):
            data = path.read_bytes()
            key = path.relative_to(source).as_posix()
            assets[key] = 'data:image/png;base64,' + base64.b64encode(data).decode()
            provenance[key] = hashlib.sha256(data).hexdigest()
    required = ['assets/desktop-1.png', 'assets/desktop-3.png', 'assets/desktop-4.png',
                'assets/desktop-5.png'] + [f'assets/collection-{i}.png' for i in range(4)]
    required += [f'film/assets/{s}.png' for s in ['files', 'search', 'appearance', 'sound', 'calendar', 'event']]
    for key in required:
        if key not in assets:
            raise FileNotFoundError(f'Missing required image: {key}')

    def js_inline(match):
        name = match.group(1)
        js = (source / name).read_text()
        if name == 'slides.js':
            table = {k.removeprefix('assets/'): v for k, v in assets.items() if k.startswith('assets/')}
            js = 'const OFFLINE_ASSETS=' + json.dumps(table) + ';\n' + js
            assert 'assets/${src}' in js
            js = js.replace('assets/${src}', '${OFFLINE_ASSETS[src]}').replace('assets/${s}', '${OFFLINE_ASSETS[s]}')
        elif name == 'app.js':
            assert "'assets/'+f.src" in js
            js = js.replace("'assets/'+f.src", 'OFFLINE_ASSETS[f.src]')
            # Sandboxed previews may deny history updates. Navigation must still render.
            js = js.replace("if(updateHash)history.replaceState(null,'','#'+(current+1));",
                            "if(updateHash){try{history.replaceState(null,'','#'+(current+1));}catch{}}")
        elif name == 'film/scenes.js':
            table = {k.removeprefix('film/assets/'): v for k, v in assets.items() if k.startswith('film/assets/')}
            js = 'const OFFLINE_ASSETS=' + json.dumps(table) + ';\n' + js
        elif name == 'film/player.js':
            assert 'film/assets/${asset}' in js
            js = js.replace('film/assets/${asset}', '${OFFLINE_ASSETS[asset]}').replace('film/assets/${a}', '${OFFLINE_ASSETS[a]}')
            for key in assets:
                if key.startswith('film/assets/'):
                    js = js.replace(key, assets[key])
        js = js.replace("history.replaceState(null,'','#'+(sceneIndex+1));", "try{history.replaceState(null,'','#'+(sceneIndex+1));}catch{}")
        js = js.replace('progress-sources.html', '#offline-sources')
        return '<script>' + re.sub(r'</script', r'<\/script', js, flags=re.I) + '</script>'

    sizes = {}
    for original, name in names.items():
        text = (source / original).read_text()
        text = re.sub(r'<link rel="stylesheet" href="([^"]+)">',
                      lambda m: '<style>' + (source / m.group(1)).read_text() + '</style>', text)
        text = re.sub(r'<script src="([^"]+)"></script>', js_inline, text)
        for old, new in names.items():
            text = text.replace('href="' + old, 'href="' + new)
        if original == 'index.html':
            text = text.replace('href="film/assets/sources.json" target="_blank"', 'href="#asset-list"')
            listing = '<details id="asset-list"><summary>内嵌素材清单</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape((source / 'film/assets/sources.json').read_text()) + '</pre></details>'
            text = text.replace('</dialog>', listing + '</dialog>')
        if original == 'progress.html':
            basis = (source / 'progress-sources.html').read_text()
            body = re.search(r'<main[^>]*>(.*?)</main>', basis, re.S).group(1)
            body = body.replace('href="progress.html"', 'href="#"')
            text = text.replace('href="progress-sources.html#datasets"', 'href="#datasets"').replace('href="progress-sources.html"', 'href="#offline-sources"')
            text = text.replace('</main>', '<details id="offline-sources"><summary>汇报依据与原论文</summary>' + body + '</details></main>', 1)
            # Dialog source navigation opens the local evidence section rather than leaving the file.
            text = text.replace('</body>', '<script>document.addEventListener("click",e=>{if(e.target.closest(\'a[href="#offline-sources"],a[href="#datasets"]\')){document.querySelector("#offline-sources").open=true;document.querySelector("#detail")?.close();}});</script></body>')
        text = text.replace('</body>', '<noscript><p style="padding:20px">交互演示需要允许 JavaScript。若飞书预览限制脚本，请下载本文件后用浏览器打开。</p></noscript></body>')
        target = output / name
        target.write_text(text)
        sizes[name] = target.stat().st_size
        if sizes[name] > 12_000_000:
            raise ValueError(f'{name} exceeds 12 MB preview limit')
    (output / 'manifest.json').write_text(json.dumps({'input_image_sha256': provenance, 'output_bytes': sizes,
        'images': 'Original PNG bytes embedded unchanged; no external rendering dependencies.',
        'scope': 'Browser offline checked separately; Feishu preview not automatically validated.'}, indent=2))
    return sizes


if __name__ == '__main__':
    print(json.dumps(bundle(sys.argv[1], sys.argv[2]), indent=2))
