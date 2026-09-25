"""轨迹单步查看器:一步步看采集到的轨迹在做什么。

读取 transitions.ndjson(按 action_index 排序的动作序列),生成一个自包含的
单文件 HTML。每一步一屏,显示:
  - 操作前截图(红点 + 十字标出点击位置)
  - 这一步的指令/语义说明(LLM 写的 "在做什么")
  - 动作详情:类型、坐标、点击的元素、输入文本
  - 操作后截图(动作产生的结果)
  - 上一步 / 下一步导航,键盘 ← → 翻页

用法:
  python tools/visualize_trajectory_html.py <run目录 或 transitions.ndjson> [-o out.html]
例:
  python tools/visualize_trajectory_html.py result_android_overnight_20260615
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_ndjson(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _find_transitions(root: Path) -> Path:
    if root.is_file() and root.name.endswith(".ndjson"):
        return root
    hits = sorted(root.rglob("transitions.ndjson"))
    if not hits:
        raise FileNotFoundError(f"在 {root} 下找不到 transitions.ndjson")
    hits.sort(key=lambda p: len(p.parts))
    return hits[0]


def _img_to_data_uri(path: Optional[Path], max_bytes: int = 4_000_000) -> Optional[str]:
    if not path or not path.exists() or path.stat().st_size > max_bytes:
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _resolve(base_candidates: List[Path], rel: str) -> Optional[Path]:
    if not rel:
        return None
    raw = Path(rel)
    for b in base_candidates:
        for cand in (b / rel, b / raw.name):
            if cand.exists():
                return cand
    if raw.exists():
        return raw
    return None


def _norm_action(act: Any) -> Dict[str, Any]:
    """action 可能是 dict 或动作列表(复合动作),归一化。"""
    parts = act if isinstance(act, list) else [act]
    parts = [a for a in parts if isinstance(a, dict)]
    if not parts:
        return {"type": "", "x": None, "y": None, "text": ""}
    first = parts[0]
    p0 = first.get("parameters", {}) or {}
    texts = [a.get("parameters", {}).get("text", "") for a in parts
             if a.get("parameters", {}).get("text")]
    types = "+".join(a.get("action_type", "") for a in parts)
    return {
        "type": types or first.get("action_type", ""),
        "x": p0.get("x"), "y": p0.get("y"),
        "text": " | ".join(texts),
    }


def build_steps(root: Path) -> Dict[str, Any]:
    tpath = _find_transitions(root)
    model_dir = tpath.parent.parent.parent  # gen_data/<model>
    bases = [Path.cwd(), root if root.is_dir() else root.parent,
             tpath.parent, model_dir]
    for sc in model_dir.rglob("screenshots"):
        bases.append(sc)
        break

    rows = _read_ndjson(tpath)
    rows = [r for r in rows if r.get("action_index") is not None]
    rows.sort(key=lambda r: r.get("action_index", 1e9))

    steps: List[Dict[str, Any]] = []
    first_shot: Optional[Path] = None
    for r in rows:
        act = _norm_action(r.get("action"))
        before = _resolve(bases, r.get("before_screenshot_path", ""))
        after = _resolve(bases, r.get("after_screenshot_path", ""))
        if first_shot is None:
            first_shot = before or after
        steps.append({
            "i": r.get("action_index"),
            "label": r.get("element_label", ""),
            "semantic": r.get("semantic_description", ""),
            "type": act["type"],
            "x": act["x"], "y": act["y"],
            "text": act["text"],
            "state_change": r.get("state_change_type", ""),
            "content": r.get("visible_content_summary", ""),
            "reason": r.get("node_decision_reason", ""),
            "before_img": _img_to_data_uri(before),
            "after_img": _img_to_data_uri(after),
        })

    # 探测截图实际像素(动作坐标与截图同一坐标系)
    dev_w, dev_h = 0, 0
    if first_shot is not None:
        try:
            from PIL import Image
            with Image.open(first_shot) as im:
                dev_w, dev_h = im.size
        except Exception:
            pass
    # 兜底:用动作坐标的最大值估算(至少不会把红点压到角落)
    if not dev_w or not dev_h:
        xs = [s["x"] for s in steps if s["x"] is not None]
        ys = [s["y"] for s in steps if s["y"] is not None]
        dev_w = max(xs) * 1.05 if xs else 720
        dev_h = max(ys) * 1.05 if ys else 1280

    app = "unknown"
    for g in model_dir.rglob("*_graph.json"):
        try:
            app = json.loads(g.read_text(encoding="utf-8")).get("app_name", "unknown")
        except Exception:
            pass
        break

    return {"app": app, "source": str(tpath),
            "dev_w": dev_w, "dev_h": dev_h, "steps": steps}


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 14px/1.6 -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  background: #11131a; color: #d7dae0; height: 100vh; overflow: hidden; }
#bar { height: 56px; display: flex; align-items: center; gap: 14px;
  padding: 0 20px; background: #181b24; border-bottom: 1px solid #272d3a; }
#bar h1 { font-size: 15px; font-weight: 600; color: #fff; }
#bar .app { color: #6cb6ff; }
#bar .spacer { flex: 1; }
#bar button { background: #232a3a; color: #d7dae0; border: 1px solid #38415680;
  border-radius: 6px; padding: 7px 16px; font-size: 14px; cursor: pointer; }
#bar button:hover:not(:disabled) { background: #2d3548; }
#bar button:disabled { opacity: .35; cursor: default; }
#counter { font-variant-numeric: tabular-nums; min-width: 90px; text-align: center;
  color: #aeb4c0; font-size: 13px; }
#main { display: flex; height: calc(100vh - 56px); }
.shots { flex: 0 0 auto; display: flex; gap: 18px; padding: 20px;
  align-items: flex-start; }
.shotbox { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.shotbox .cap { font-size: 12px; color: #8b909c; }
.shotwrap { position: relative; height: calc(100vh - 130px); }
.shotwrap img { height: 100%; border: 1px solid #272d3a; border-radius: 8px;
  display: block; }
.marker { position: absolute; width: 26px; height: 26px; border: 2px solid #ff4d4f;
  border-radius: 50%; background: #ff4d4f33; transform: translate(-50%,-50%);
  pointer-events: none; box-shadow: 0 0 0 4px #ff4d4f22; }
.marker::before, .marker::after { content: ''; position: absolute;
  background: #ff4d4f; }
.marker::before { left: 50%; top: -8px; width: 1.5px; height: 42px;
  transform: translateX(-50%); }
.marker::after { top: 50%; left: -8px; height: 1.5px; width: 42px;
  transform: translateY(-50%); }
.arrow { flex: 0 0 auto; align-self: center; font-size: 28px; color: #4b5366; }
#info { flex: 1; padding: 24px 26px; overflow-y: auto; border-left: 1px solid #272d3a;
  background: #141720; }
#info .step-no { font-size: 13px; color: #6b7180; letter-spacing: .04em; }
#info .what { font-size: 18px; font-weight: 600; color: #fff; margin: 4px 0 14px; }
.semantic { background: #19202c; border-left: 3px solid #6cb6ff; padding: 12px 14px;
  border-radius: 0 7px 7px 0; color: #c6ccd6; margin-bottom: 18px; }
.row { display: flex; padding: 7px 0; border-bottom: 1px solid #1d2330; font-size: 13px; }
.row .k { color: #8b909c; width: 92px; flex-shrink: 0; }
.row .v { color: #e3e6ec; word-break: break-word; }
.chip { display: inline-block; padding: 2px 9px; border-radius: 5px; font-size: 12px;
  font-weight: 600; }
.c-new_page { background: #1f3a28; color: #7ee787; }
.c-new_overlay { background: #3a3520; color: #ffd866; }
.c-new_dialog { background: #3a2535; color: #ff8fd0; }
.c-local_state_change { background: #1f3140; color: #6cb6ff; }
.c-mode_or_tab_change { background: #2b2540; color: #c9a4ff; }
.c-def { background: #2c3344; color: #aeb4c0; }
.act { font-family: 'SF Mono', Consolas, monospace; font-size: 13px; color: #ffd866; }
#empty { padding: 40px; color: #8b909c; }
"""

_JS = r"""
const DATA = __PAYLOAD__;
const S = DATA.steps;
let cur = 0;
const DEV_W = DATA.dev_w || 720, DEV_H = DATA.dev_h || 1280;  // 截图坐标系

function esc(s){ return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function chip(t){
  const known=['new_page','new_overlay','new_dialog','local_state_change','mode_or_tab_change'];
  const c = known.includes(t)?('c-'+t):'c-def';
  return `<span class="chip ${c}">${esc(t||'?')}</span>`;
}

function render(){
  const s = S[cur];
  document.getElementById('counter').textContent = `第 ${cur+1} / ${S.length} 步`;
  document.getElementById('prev').disabled = cur===0;
  document.getElementById('next').disabled = cur===S.length-1;

  // 左:操作前(带点击标记) + 箭头 + 操作后
  let marker = '';
  if(s.x!=null && s.y!=null){
    // 坐标按设备分辨率换算成百分比,定位到图片上
    const px = (s.x/DEV_W*100).toFixed(2), py = (s.y/DEV_H*100).toFixed(2);
    marker = `<div class="marker" style="left:${px}%;top:${py}%"></div>`;
  }
  const beforeImg = s.before_img
    ? `<div class="shotwrap"><img src="${s.before_img}">${marker}</div>`
    : `<div class="shotwrap" style="width:300px;display:flex;align-items:center;justify-content:center;color:#6b7180">无截图</div>`;
  const afterImg = s.after_img
    ? `<div class="shotwrap"><img src="${s.after_img}"></div>`
    : `<div class="shotwrap" style="width:300px;display:flex;align-items:center;justify-content:center;color:#6b7180">无截图</div>`;

  document.getElementById('shots').innerHTML =
    `<div class="shotbox"><div class="cap">操作前(红点=点击位置)</div>${beforeImg}</div>
     <div class="arrow">→</div>
     <div class="shotbox"><div class="cap">操作后</div>${afterImg}</div>`;

  // 右:这一步在做什么
  let coord = (s.x!=null) ? ` @(${s.x}, ${s.y})` : '';
  let info = `<div class="step-no">动作 #${s.i}</div>
    <div class="what">${esc(s.label) || esc(s.type) || '(无标签)'}</div>`;
  if(s.semantic) info += `<div class="semantic">${esc(s.semantic)}</div>`;
  info += `<div class="row"><span class="k">动作</span><span class="v act">${esc(s.type)}${coord}</span></div>`;
  if(s.text) info += `<div class="row"><span class="k">输入文本</span><span class="v act">${esc(s.text)}</span></div>`;
  info += `<div class="row"><span class="k">状态变化</span><span class="v">${chip(s.state_change)}</span></div>`;
  if(s.content) info += `<div class="row"><span class="k">页面内容</span><span class="v">${esc(s.content)}</span></div>`;
  if(s.reason) info += `<div class="row"><span class="k">判定理由</span><span class="v">${esc(s.reason)}</span></div>`;
  document.getElementById('info').innerHTML = info;
}

function go(d){ const n=cur+d; if(n>=0 && n<S.length){ cur=n; render(); } }
document.getElementById('prev').onclick=()=>go(-1);
document.getElementById('next').onclick=()=>go(1);
document.addEventListener('keydown', e=>{
  if(e.key==='ArrowLeft') go(-1);
  if(e.key==='ArrowRight'||e.key===' ') { e.preventDefault(); go(1); }
});
if(S.length) render();
else document.getElementById('main').innerHTML='<div id="empty">没有可显示的步骤(transitions.ndjson 为空)</div>';
"""


def render_html(payload: Dict[str, Any]) -> str:
    js = _JS.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    n = len(payload["steps"])
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>轨迹单步查看 · {payload['app']}</title>
<style>{_CSS}</style></head>
<body>
<div id="bar">
  <h1>轨迹回放 · <span class="app">{payload['app']}</span></h1>
  <span style="color:#8b909c;font-size:13px">共 {n} 步</span>
  <div class="spacer"></div>
  <button id="prev">‹ 上一步</button>
  <span id="counter">—</span>
  <button id="next">下一步 ›</button>
</div>
<div id="main">
  <div class="shots" id="shots"></div>
  <div id="info"></div>
</div>
<script>{js}</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="轨迹单步查看器")
    ap.add_argument("run_dir", help="run 目录 / transitions.ndjson")
    ap.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    args = ap.parse_args()

    root = Path(args.run_dir)
    payload = build_steps(root)
    out = Path(args.out) if args.out else (
        (root if root.is_dir() else root.parent) / "trajectory_steps.html")
    out.write_text(render_html(payload), encoding="utf-8")
    print(f"[OK] {payload['app']}: {len(payload['steps'])} 步 -> {out}")
    print(f"     浏览器打开: {out.resolve()}")


if __name__ == "__main__":
    main()
