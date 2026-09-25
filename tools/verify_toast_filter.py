"""Verify the grounding prompt now EXCLUDES app-external system notifications/toasts
(2026-07-06 用户: app 外的提示框在过滤阶段就丢掉). Real VLM on a saved frame.

The frame result_foldcheck10/.../8003071f is Privacy>Connectivity WITH an
"Ubuntu Software 'Software' is ready" toast overlapping the top — which HIJACKED
grounding (it returned only the toast, missing the real page -> a junk node +
mis-attributed edge). With the fix, grounding must skip the toast and see the
real page (sidebar + Connectivity content).

Usage:  python tools/verify_toast_filter.py
"""
import glob
import sys

sys.path.insert(0, ".")

from gui_rewalk.env.gui_gen_agent import GUIGenAgent  # noqa: E402
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception  # noqa: E402

FRAME = glob.glob("result_foldcheck10/20260706/setting/node_artifacts/"
                  "8003071f*/screenshot.png")


def main():
    if not FRAME:
        print("SKIP: toast frame not found"); return
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus", use_ark=False,
                        max_tokens=2500, temperature=0.1)
    perc = VisualPerception(None, agent=agent, use_ocr=False)
    perc.use_vlm_grounding = True
    els = perc.detect_and_name(open(FRAME[0], "rb").read())
    names = [e.name for e in els]
    toast = [n for n in names if "software" in (n or "").lower()
             or "is ready" in (n or "").lower()]
    page = [n for n in names if n in ("Connectivity", "Thunderbolt",
                                      "Connectivity Checking", "Diagnostics")]
    print(f"元素数: {len(els)}")
    print(f"toast 元素 (应为 0): {len(toast)} {toast}")
    print(f"真页面元素命中 (应 >= 3): {len(page)} {page}")
    ok = (len(toast) == 0 and len(page) >= 3)
    print("TOAST-FILTER VERIFY:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
