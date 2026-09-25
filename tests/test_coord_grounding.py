"""坐标输出对照: 强制 Qwen 只看原图、不给a11y元素列表, 直接输出点击坐标,
把落点用红点标在图上看准不准。
用法: PYTHONUTF8=1 PYTHONPATH=.:OSWorld python tests/test_coord_grounding.py
"""
import os, sys, json, re
sys.path.insert(0, "."); sys.path.insert(0, "OSWorld"); sys.path.insert(0, "gui_rewalk")
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from gui_rewalk.env.gui_gen_agent import GUIGenAgent

NODE = "result_setting_qwen_0603_noopfix/gen_data/Qwen/0/nodes/06b0eb0e5f70a8a8"
OUT = "collections/_som_demo"; os.makedirs(OUT, exist_ok=True)
img = Image.open(os.path.join(NODE, "screenshot.png")).convert("RGB")
sw, sh = img.size

agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus",
                    max_tokens=800, top_p=0.9, temperature=0.0,
                    action_space="gen_data", observation_type="screenshot",
                    enable_ocr=False, max_trajectory_length=0, max_retry=2,
                    enable_thinking=False)

# several targets to probe coordinate grounding
TASKS = [
    ("workspaces6", "把 'Number of Workspaces'(工作区数量) 设为6 —— 你要点哪里?"),
    ("fixed", "选择 'Fixed number of workspaces'(固定数量工作区) 这个单选项。"),
    ("sound", "点击左侧边栏的 'Sound'(声音) 设置项。"),
]

def ask_xy(task):
    prompt = (
        "你是GUI操作智能体, 只能看截图(没有元素列表), 必须用**像素坐标**操作。\n"
        f"图尺寸 {sw}x{sh}。{task}\n"
        "输出你要点击位置的坐标, 用0-1000归一化坐标系。只回JSON: "
        '{"thought":"...","x":<0-1000>,"y":<0-1000>}'
    )
    r, *_ = agent.predict_mm(prompt, [np.array(img)])
    try:
        o = json.loads(r[r.index("{"):r.rindex("}") + 1])
        x, y = float(o.get("x")), float(o.get("y"))
        # 0-1000 normalized -> pixels (de-norm, same as executor)
        if x <= 1000 and y <= 1000:
            px, py = int(x / 1000 * sw), int(y / 1000 * sh)
        else:
            px, py = int(x), int(y)
        return px, py, o.get("thought", ""), r
    except Exception as e:
        return None, None, f"(parse fail {e})", r

annotated = img.copy()
d = ImageDraw.Draw(annotated)
try: font = ImageFont.truetype("arial.ttf", 18)
except Exception: font = ImageFont.load_default()
COLORS = [(220, 30, 30), (30, 120, 220), (30, 170, 60)]
for i, (tag, task) in enumerate(TASKS):
    px, py, th, raw = ask_xy(task)
    print(f"\n===== {tag} =====\n  -> ({px},{py})  thought: {th[:90]}")
    if px is None:
        print("  raw:", raw[:200]); continue
    c = COLORS[i % len(COLORS)]
    r = 14
    d.ellipse([px - r, py - r, px + r, py + r], outline=c, width=4)
    d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=c)
    d.text((px + 16, py - 10), f"{i+1}.{tag}", fill=c, font=font)
out = os.path.join(OUT, "coord_clicks.png")
annotated.save(out)
print(f"\n[info] wrote {out}")
