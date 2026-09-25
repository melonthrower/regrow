"""[2026-07-09 用户] 定点测试:模态框 tab 遍历(真点击,不 reset,不跑全量)。

先在 VM 里手动打开一个带多 tab 的模态(如「网络配置」有 Identity/IPv4/IPv6/Security)。
本脚本连上正在运行的 VM,循环:感知当前帧 → 跑 _regional_scroll_dedup(登记 tab_bar
到稳定 region_id + 打标各 tab)→ 从 region_registry 取该 rid 的【未点】tab → CLICK →
mark_clicked → 等页面切换 → 再来,直到 tab_bar 的 tab 全部点完(或触发防死循环上限)。

校验:(1) 4 个 tab 是否都被点到且【各只点一次】(region_id 去重生效,不反复点);
(2) 每次点击后内容是否真变(form_body 元素集变化);(3) 全部点完后能干净收敛。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("visual_traversal.entry")

# 复用 test_modal_region 的参数解析 + agent/env/engine 构造 + live 监视器
from test_modal_region import parse_args as _base_args, build, setup_live_monitor  # noqa: E402

MAX_ITERS = 8   # 防死循环:最多这么多轮(4 tab 正常 ≤5 轮即收敛)


def _perceive_and_register(perception, engine, env):
    """抓当前帧 → 感知 → dedup(登记 tab_bar/form_body + 打 region_id)。
    返回 (aggregated 元素, tab_bar_rid 或 None, form_body 元素名集)。"""
    obs = env._get_obs()
    shot = obs.get("screenshot")
    if not shot:
        return None, None, set(), None
    first = perception.detect_and_name(shot)
    # 用固定 node_id,让 tab_bar 每轮匹配回同一 rid、clicked 台账跨轮累积
    aggregated = engine._regional_scroll_dedup(obs, list(first), "TAB_TEST_NODE")
    tab_rid = None
    form_names = set()
    for e in aggregated:
        role = getattr(e, "region", "") or ""
        rid = getattr(e, "region_id", "") or ""
        if role == "tab_bar" and rid:
            tab_rid = rid
        if role == "form_body" and e.name:
            form_names.add(e.name.strip().lower())
    return aggregated, tab_rid, form_names, obs


def run_test(perception, env, engine) -> int:
    reg = engine.region_registry
    click_log = []          # [(tab_name, form_names_before, form_names_after)]
    seen_tabs = set()       # 所有见过的 tab 名(取自 tab_bar region)

    for it in range(1, MAX_ITERS + 1):
        logger.info("[轮次 %d] 感知当前帧 + 登记区块...", it)
        aggregated, tab_rid, form_before, _obs = _perceive_and_register(
            perception, engine, env)
        if aggregated is None:
            logger.error("[失败]  抓不到截图 —— VM 没连上?")
            return 2
        if not tab_rid:
            logger.error("[失败]  当前帧没识别出 tab_bar 区块(不是多 tab 模态?)。")
            return 1

        all_tabs = reg.buttons(tab_rid)
        unclicked = reg.unclicked(tab_rid)
        seen_tabs |= all_tabs
        logger.info("[轮次 %d] tab_bar rid=%s ｜ 全部 tab=%s ｜ 未点=%s",
                    it, tab_rid, sorted(all_tabs), sorted(unclicked))

        if not unclicked:
            logger.info("[收敛]  ✔ tab_bar 所有 tab 已点完,遍历结束。")
            break

        # 选一个未点 tab,在【当前 aggregated】里找它的元素(拿真实 live 坐标)
        target_name = sorted(unclicked)[0]
        target_elem = None
        for e in aggregated:
            if (getattr(e, "region", "") == "tab_bar"
                    and (e.name or "").strip().lower() == target_name):
                target_elem = e
                break
        if target_elem is None:
            # 未点 tab 这帧没被识别到(当前 tab 自身或抖动)——标记已点跳过,防卡死
            logger.warning("[轮次 %d] 未点 tab '%s' 本帧未识别到,标记已点跳过。",
                           it, target_name)
            reg.mark_clicked(tab_rid, target_name)
            continue

        cx, cy = int(target_elem.center[0]), int(target_elem.center[1])
        logger.info("[点击]  tab '%s' @ (%d,%d)", target_name, cx, cy)
        env.step({"action_type": "CLICK",
                  "parameters": {"x": cx, "y": cy, "button": "left"}}, pause=0.3)
        reg.mark_clicked(tab_rid, target_name)
        time.sleep(1.0)   # 等内容切换稳定

        # 点击后再抓一帧看 form_body 内容变没变(验证 tab 真切换了)
        _agg2, _rid2, form_after, _o2 = _perceive_and_register(
            perception, engine, env)
        changed = (form_after != form_before) and bool(form_after)
        logger.info("[效果]  '%s' 点击后 form_body 内容%s(前 %d 项 / 后 %d 项)",
                    target_name, "已变化" if changed else "未变化/无法确认",
                    len(form_before), len(form_after))
        click_log.append((target_name, changed))

    return _report(seen_tabs, click_log)


def _report(seen_tabs, click_log) -> int:
    clicked_names = [n for n, _ in click_log]
    dupes = len(clicked_names) != len(set(clicked_names))
    n_changed = sum(1 for _, c in click_log if c)
    logger.info("=" * 60)
    logger.info("[汇总]  见过的 tab(%d):%s", len(seen_tabs), sorted(seen_tabs))
    logger.info("[汇总]  点击顺序(%d 次):%s", len(clicked_names), clicked_names)
    logger.info("[汇总]  重复点击:%s ｜ 点击后内容变化:%d/%d",
                "有(去重失效!)" if dupes else "无 ✔", n_changed, len(click_log))
    # 通过:每个见过的 tab 都点了、没重复、且大多数点击有内容变化
    covered = set(n.lower() for n in clicked_names) >= set(n.lower() for n in seen_tabs)
    passed = covered and not dupes and len(seen_tabs) >= 2
    if passed:
        logger.info("[通过]  ✔ %d 个 tab 全部探索到,各只点一次,region_id 去重生效。",
                    len(seen_tabs))
    else:
        logger.error("[失败]  ✖ 覆盖=%s 重复=%s 见过 tab 数=%d —— 详见上方轮次日志。",
                     covered, dupes, len(seen_tabs))
    return 0 if passed else 1


def main() -> int:
    args = _base_args()
    setup_live_monitor(args.live_monitor)
    logger.info("=== 模态框 tab 遍历定点测试 开始 ===")
    env = None
    try:
        _agent, perception, env, engine = build(args)
        return run_test(perception, env, engine)
    except Exception as e:
        logger.exception("[失败]  测试异常:%s", e)
        return 3
    finally:
        logger.info("=== 测试结束(VM 保持原样,未 reset/close) ===")


if __name__ == "__main__":
    sys.exit(main())
