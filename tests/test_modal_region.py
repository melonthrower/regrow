"""[2026-07-09 用户] 定点测试:模态框区块化 + 滚动 + tab 去重(不跑全量遍历)。

用法:先在 VM 里手动打开某个模态弹窗(如「有线网络设置」,最好是需要滚动的高模态),
再跑本脚本。它连上【正在运行的】VM(不 reset,不冲掉你的页面),抓当前帧,跑真实
perception + 我改过的 _regional_scroll_dedup,校验:
  (1) 是否识别为模态;(2) 分出哪些子区块 + 各自 scrollable;(3) 每个区块是否打上
  region_id(登记成功);(4) form_body 高时是否滚出 below-fold 元素;(5) tab_bar
  是否打标(→ tab 能按名去重,不再反复点)。

日志走和真实遍历同一套(tee 到 _scratch/live_*.log + 自动开 live_status 监视器窗口),
所以调试台能实时看到 [模态]/[区块]/[滚动]/[通过]/[失败] 标签。
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("visual_traversal.entry")   # 复用监视器认得的 logger 名


def parse_args():
    p = argparse.ArgumentParser(description="定点测试模态框区块化/滚动/去重")
    p.add_argument("--path_to_vm", default="OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx")
    p.add_argument("--vm_provider", default="vmware")
    p.add_argument("--model", default="Qwen")
    p.add_argument("--model_version", default="qwen3.7-plus")
    p.add_argument("--max_tokens", type=int, default=1500)
    p.add_argument("--temperature", type=float, default=0.5)
    p.add_argument("--enable_thinking", action="store_true")
    p.add_argument("--ocr_model_path", default="OmniParser/weights/icon_detect/model.pt")
    p.add_argument("--ocr_engine", default="easyocr")
    p.add_argument("--ocr_lang", default="en,ch_sim")
    p.add_argument("--no_ocr", action="store_true")
    p.add_argument("--vlm_grounding", action="store_true", default=True)
    p.add_argument("--no_live_monitor", dest="live_monitor", action="store_false", default=True)
    return p.parse_args()


def setup_live_monitor(live_monitor: bool) -> str:
    """Tee logs 到 _scratch/live_*.log(UTF-8)并自动开监视器窗口。返回日志路径。"""
    os.makedirs("_scratch", exist_ok=True)
    tag = f"modaltest_{os.getpid()}"
    log_path = os.path.join("_scratch", f"live_{tag}.log")
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)
    logger.info("live log -> %s", log_path)
    if live_monitor:
        mon = os.path.join(REPO_ROOT, "tools", "live_status.py")
        if os.path.exists(mon):
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            try:
                subprocess.Popen([sys.executable, mon, log_path], **kwargs)
                logger.info("live monitor window opened (tools/live_status.py)")
            except Exception as e:
                logger.warning("live monitor skipped (%s)", e)
    return log_path


def build(args):
    """构造与真实遍历一致的 agent / perception / env / engine。env 只连不 reset。"""
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
    from gui_rewalk.env.utils import get_yolo_model
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
    from gui_rewalk.src.core.visual_traversal import visual_filter as _vf

    # 桌面:关掉系统条裁剪(顶部是应用菜单栏,不是系统条)——与 run_full 一致
    _vf.SYSTEM_UI_BAND_ENABLED = False

    agent = GUIGenAgent(model=args.model, model_version=args.model_version,
                        max_tokens=args.max_tokens, temperature=args.temperature,
                        enable_thinking=args.enable_thinking)
    yolo = get_yolo_model(args.ocr_model_path)
    perception = VisualPerception(yolo, agent=agent, caption_mp=None,
                                  use_ocr=not args.no_ocr, ocr_engine=args.ocr_engine,
                                  ocr_languages=[s for s in args.ocr_lang.split(",") if s])
    perception.use_vlm_grounding = getattr(args, "vlm_grounding", True)

    # 连上正在运行的 VM(__init__ 只 start_emulator + 建 controller,不 revert 快照)
    env = DesktopGUIGenEnv(
        provider_name=args.vm_provider, path_to_vm=args.path_to_vm,
        action_space=agent.action_space, screen_size=(1920, 1080),
        headless=False, os_type="Ubuntu")

    out = os.path.join("_scratch", f"modaltest_out_{os.getpid()}")
    os.makedirs(out, exist_ok=True)
    engine = VisualTraversalEngine(
        env=env, agent=agent, perception=perception, app_name="setting",
        output_root=out, region_dedup=True, stitch_node_image=False)
    return agent, perception, env, engine


def run_test(perception, env, engine) -> int:
    """抓当前帧 → 感知 → 跑 _regional_scroll_dedup → 校验并打标签日志。返回退出码。"""
    logger.info("[取帧]  抓取 VM 当前画面(你手动跳转到的页面)...")
    obs = env._get_obs()
    shot = obs.get("screenshot")
    if not shot:
        logger.error("[失败]  抓不到截图 —— VM 没连上或 guest server 没响应")
        return 2

    # 1) 真感知(会设置 last_is_modal + 分割缓存,与注册路径一致)
    first = perception.detect_and_name(shot)
    is_modal = getattr(perception, "last_is_modal", False)
    logger.info("[模态]  当前帧 is_modal=%s ｜ 顶帧感知到 %d 个元素", is_modal, len(first))
    if not is_modal:
        logger.warning("[失败]  当前帧不是模态框!请在 VM 里打开一个弹窗(如有线网络设置)再重跑。")
        # 仍继续跑 dedup 看普通页行为,但主校验判失败

    # 2) 看这一帧分出哪些区块 + scrollable(直接调分割,复用缓存,不额外花 VLM)
    regions = engine._segment_regions_cached(shot)
    logger.info("[区块]  分出 %d 个子区块:", len(regions))
    for r in regions:
        logger.info("[区块]    role=%-16s scrollable=%s  note=%s",
                    r.get("role"), r.get("scrollable"), (r.get("note") or "")[:30])

    # 3) 跑我改过的 dedup(会打 region_id / 登记 / form_body 可滚则真滚 VM)
    n_before = len(first)
    logger.info("[滚动]  调用 _regional_scroll_dedup(会对 content/form_body 尝试滚动)...")
    # [2026-07-09] 钩住 detect_and_name:把滚动每一步喂给 grounding 的【整帧】存盘,
    # 用来看光标停在哪、气泡有没有盖住 tab(区块长图是裁剪块,看不到这些)。
    out_dir0 = getattr(engine, "output_root", "_scratch")
    _orig_detect = perception.detect_and_name
    _frame_ctr = {"n": 0}

    def _detect_spy(shot_bytes, *a, **kw):
        i = _frame_ctr["n"]
        _frame_ctr["n"] += 1
        try:
            with open(os.path.join(out_dir0, f"scrollframe_{i:02d}.png"), "wb") as f:
                f.write(shot_bytes)
        except Exception:
            pass
        return _orig_detect(shot_bytes, *a, **kw)

    perception.detect_and_name = _detect_spy
    try:
        aggregated = engine._regional_scroll_dedup(obs, list(first), "TEST_MODAL")
    finally:
        perception.detect_and_name = _orig_detect
    logger.info("[滚动]  滚动期间整帧存了 %d 张(scrollframe_*.png)", _frame_ctr["n"])
    n_after = len(aggregated)

    # 4) 校验
    tagged = [e for e in aggregated if getattr(e, "region_id", "")]
    by_role = {}
    for e in aggregated:
        role = getattr(e, "region", "") or "?"
        by_role[role] = by_role.get(role, 0) + 1
    below_fold = [e for e in aggregated if getattr(e, "scroll_steps", 0) > 0]
    tab_tagged = [e for e in aggregated
                  if (getattr(e, "region", "") in ("tab_bar",)) and getattr(e, "region_id", "")]

    logger.info("[校验]  元素数 %d → %d(滚出 below-fold %d 个)", n_before, n_after, len(below_fold))
    logger.info("[校验]  打上 region_id 的元素 %d/%d ｜ 各区块分布:%s",
                len(tagged), n_after, by_role)
    # [2026-07-09] 逐元素转储:name / bbox_xywh / scroll_steps / region / region_id
    # —— 用来判断"below-fold"是不是真在下方(y 变大),还是固定 chrome 被误收。
    logger.info("[明细]  region bbox:%s",
                {r.get("role"): r.get("bbox") for r in regions})
    for e in aggregated:
        bb = getattr(e, "bbox_xywh", None)
        logger.info("[明细]    %-24s bbox=%s cy=%s step=%d region=%s rid=%s",
                    (e.name or "")[:24], bb,
                    (e.center[1] if getattr(e, "center", None) else "?"),
                    getattr(e, "scroll_steps", 0), getattr(e, "region", ""),
                    (getattr(e, "region_id", "") or "")[:6])
    if below_fold:
        for e in below_fold[:8]:
            logger.info("[校验]    below-fold: %-24s (scroll_steps=%d region=%s)",
                        (e.name or "")[:24], e.scroll_steps, getattr(e, "region", ""))

    # [2026-07-09] 把这次滚动拼出的长图(各区块 composite)落盘 —— 路径 A 只把它存进
    # engine._region_composites(内存),不落盘。存出来直接看"滚动长图"长啥样。
    comps = getattr(engine, "_region_composites", {}) or {}
    out_dir = getattr(engine, "output_root", "_scratch")
    logger.info("[长图]  本次滚动拼出 %d 张区块长图:", len(comps))
    for role, png in comps.items():
        p = os.path.join(out_dir, f"composite_{role}.png")
        try:
            with open(p, "wb") as f:
                f.write(png)
            try:
                from PIL import Image as _I
                import io as _io
                w, h = _I.open(_io.BytesIO(png)).size
            except Exception:
                w = h = "?"
            logger.info("[长图]    %-16s %sx%s → %s", role, w, h, p)
        except Exception as ex:
            logger.warning("[长图]    %s 存盘失败:%s", role, ex)
    # 首帧原图也存一份做对照
    try:
        p0 = os.path.join(out_dir, "top_frame.png")
        with open(p0, "wb") as f:
            f.write(shot)
        logger.info("[长图]    top_frame(首帧原图) → %s", p0)
    except Exception:
        pass

    # 通过判据
    ok_modal = is_modal
    ok_tagged = len(tagged) > 0
    ok_tabdedup = (len(tab_tagged) > 0) or all(r.get("role") != "tab_bar" for r in regions)
    passed = ok_modal and ok_tagged
    if passed:
        logger.info("[通过]  ✔ 模态识别=%s ｜ 区块打标=%s(%d 元素带 region_id)｜ tab打标=%s",
                    ok_modal, ok_tagged, len(tagged), bool(tab_tagged))
        logger.info("[通过]  ✔ 若元素数增加,则高模态 below-fold 已被滚出;tab 带 region_id "
                    "→ 点一次后全局按名去重,不再反复点。")
    else:
        logger.error("[失败]  ✖ 模态识别=%s ｜ 区块打标=%s —— 详见上方 [区块]/[校验]。",
                     ok_modal, ok_tagged)
    return 0 if passed else 1


def main() -> int:
    args = parse_args()
    setup_live_monitor(args.live_monitor)
    logger.info("=== 模态框区块化定点测试 开始 ===")
    env = None
    try:
        _agent, perception, env, engine = build(args)
        return run_test(perception, env, engine)
    except Exception as e:
        logger.exception("[失败]  测试异常:%s", e)
        return 3
    finally:
        # 只释放本进程的 controller,不 close VM(免得关掉你手动开的窗口/环境)
        logger.info("=== 测试结束(VM 保持原样,未 reset/close) ===")


if __name__ == "__main__":
    sys.exit(main())
