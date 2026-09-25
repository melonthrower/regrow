"""遍历/采集 实时状态窗口。tail 引擎日志 -> 翻译成自然语言 feed(中文)。
只读、不碰引擎、零风险。遍历和之后的采集共用同一套日志,都适用。

用法:
    python tools/live_status.py                 # 自动跟最新的 _scratch/*.log
    python tools/live_status.py <日志路径>       # 指定日志
在【另一个终端窗口】跑它,一边看遍历、一边看它在做什么。
"""
import argparse
import ctypes
import glob
import json
import os
import re
import sys
import time
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _names(lst, total, n=3):
    """'['Network','Bluetooth','Sound']', 8 -> 'Network/Bluetooth/Sound 等8个'。"""
    items = re.findall(r"'([^']*)'|\"([^\"]*)\"", lst or "")
    flat = [a or b for a, b in items if (a or b).strip()]
    if not flat:
        return "(空)"
    head = "/".join(flat[:n])
    return f"{head} 等{total}个" if int(total) > len(flat[:n]) else head




# 日志行 -> (标签, 自然语言) 规则。按顺序匹配,第一个命中即用。
RULES = [
    (r"Startup reset: launching '(\w+)'", "[启动]", lambda m: f"启动应用 {m.group(1)} ..."),
    (r"Startup reset: '(\w+)' is ready", "[就绪]", lambda m: f"{m.group(1)} 就绪"),
    (r"Startup reset: killing", "[重启]", lambda m: "hard-reset:关闭应用准备重启(回根恢复)"),
    (r"\[M1\] graph router ACTIVE", "[路由]", lambda m: "图路由器已激活(唯一回退机制)"),
    (r"\[进度\] 节点 (\d+)\((\d+)待探\) · 区块 (\d+) · 导航按钮 (\d+)/(\d+)已探\((\d+)%\)", "[进度]",
     lambda m: f"进度 ▶ 节点 {m.group(1)}个(待探 {m.group(2)}) ｜ 区块 {m.group(3)}个 ｜ 导航按钮 {m.group(4)}/{m.group(5)} 已探 {m.group(6)}%"),
    # [2026-07-08 用户] [所在] 主显【整页概括名】(page=「打印机」);区块只留极简计数
    # (侧栏N项/内容M项)做可观测性兜底。页面名空(模态偶发)才退回显示区块名。
    (r"\[region-id\] arrival page=「([^」]*)」 rset=.*侧栏\[([^\]]*)\]\((\d+)\)=\[[^\]]*\] \| 内容\[([^\]]*)\]\((\d+)\)=\[[^\]]*\]", "[所在]",
     lambda m: f"当前所在 … 「{m.group(1)}」（侧栏{m.group(3)}项/内容{m.group(5)}项）"
               if m.group(1).strip()
               else f"当前所在 … 侧栏{m.group(3)}项/内容{m.group(5)}项"
                    + (f"(侧栏「{m.group(2)}」)" if m.group(2).strip() else "")),
    (r"\[region-id\] arrival .*侧栏\((\d+)\)=(\[[^\]]*\]) \| 内容\((\d+)\)=(\[[^\]]*\])", "[识别]",
     lambda m: f"当前页 … 侧栏:{_names(m.group(2), m.group(1))} ｜ 内容:{_names(m.group(4), m.group(3))}"),
    (r"\[region-id\] arrival rset=(\S+) .*left=(\d+) right=(\d+)", "[识别]",
     lambda m: f"正在识别当前页 … 侧栏{m.group(2)}项/内容{m.group(3)}项,区块集={m.group(1)}"),
    (r"registered NEW visual state (\w{8})\w* 页面「([^」]*)」\((\d+) clickable", "[新页]",
     lambda m: f"注册【新页面】「{m.group(2)}」{m.group(1)}（{m.group(3)}个可点元素）"),
    (r"registered NEW visual state (\w{8})\w* \((\d+) clickable", "[新页]",
     lambda m: f"注册【新页面】{m.group(1)}（{m.group(2)}个可点元素）"),
    (r"\[region-id\] register: .*SAME as (\w{8})\w* -> MERGE", "[重访]",
     lambda m: f"识别为【已知页面】{m.group(1)}(重访,不新建)"),
    (r"\[region-id\] register: .*matched NO node -> NEW (\w{8})", "[新页]",
     lambda m: f"没见过的新页面 → 建 {m.group(1)}"),
    (r"\[merge-shot\] \S+ matched=(\w{8}) rset=(\[[^\]]*\])", "[取证]",
     lambda m: f"合并进 {m.group(1)}({m.group(2).count(':')}个区块匹配上)"),
    (r"LEDGER-AUTHORITATIVE: exploring '([^']+)'", "[账本]",
     lambda m: f"账本还有没点的候选 → 继续点「{m.group(1)}」"),
    (r"explorer: click '([^']+)' \(([^)]*)\)", "[点击]",
     lambda m: f"决定点击 →「{m.group(1)}」　（因为:{m.group(2)}）"),
    (r"explorer: click '([^']+)'", "[点击]",
     lambda m: f"决定点击 →「{m.group(1)}」"),
    (r"explorer: page done", "[页完]", lambda m: "当前页:该点的都点了"),
    (r"\[目标\] 下一步: 前往 (\w{8})\w* 点「([^」]*)」\(账本还剩 (\d+)", "[目标]",
     lambda m: f"下一步:去 {m.group(1)} 点「{m.group(2)}」(账本还剩 {m.group(3)} 个候选)"),
    (r"router: plan (\w{8})\w* -> (\w{8})\w* = (\d+) hop\(s\) \[路径: ([^\]]*)\]", "[路由]",
     lambda m: f"规划路径 {m.group(3)} 跳:{m.group(4)}  → 到 {m.group(2)}"),
    (r"router: plan (\w{8})\w* -> (\w{8})\w* = (\d+) hop", "[路由]",
     lambda m: f"回溯/导航:{m.group(1)} → {m.group(2)}（{m.group(3)}跳）"),
    (r"router: hop '([^']+)' expected (\w{8})\w* got (\w+)", "[偏]",
     lambda m: f"点「{m.group(1)}」本应到 {m.group(2)},实际到 {str(m.group(3))[:8]} → 重新规划"),
    (r"router: back-ascent .* reached target (\w{8})", "[返回]",
     lambda m: f"点返回键往上退 → 到达目标 {m.group(1)}"),
    (r"router: back-ascent (\w{8})\w* -> (\w{8})", "[返回]",
     lambda m: f"点返回键退一层:{m.group(1)} → {m.group(2)}"),
    (r"no progress \+ back didn't help.* abort", "[放弃]", lambda m: "退不动 → 放弃这条路,准备 hard-reset"),
    (r"\[身份质检\] 疑似过度分裂: 新页 (\w{8})\w* 与 (\w{8})\w* 视觉极近\(pHash=(\d+)\)", "[分裂?]",
     lambda m: f"⚠ 疑似过度分裂:新页 {m.group(1)} 与 {m.group(2)} 视觉几乎相同(pHash={m.group(3)}) 却判成不同页!"),
    (r"\[身份质检\] 疑似过度合并: 本帧并入 (\w{8})\w* 但视觉差异大\(pHash=(\d+)\)", "[合并?]",
     lambda m: f"⚠ 疑似过度合并:并入 {m.group(1)} 但两帧视觉差异大(pHash={m.group(2)})"),
    (r"backtrack to (\w{8})\w* reported success but landed on (\w{8})", "[串页!]",
     lambda m: f"串页!以为到了 {m.group(1)},实际在 {m.group(2)}"),
    (r"\[reconcile\] 串页自纠: 以为在 (\w{8})\w* 实际在 (\w{8})", "[串页自纠]",
     lambda m: f"以为在 {m.group(1)},其实在 {m.group(2)} → 已重定位,候选留原页账本待可信路径"),
    (r"\[reconcile\] QUARANTINE 串页边 (\w{8})\w*->(\w{8})\w* \(反复 (\d+)", "[隔离]",
     lambda m: f"串页边 {m.group(1)}→{m.group(2)} 反复{m.group(3)}次 → 隔离,router 规划绕开"),
    (r"click_effect.*no_effect", "[死点]", lambda m: "点击【无效】(死点,页面没反应)"),
    (r"QUARANTINE edge", "[隔离]", lambda m: "隔离一条可疑的边(串页导致)"),
    (r"ABNORMAL BUTTON '([^']+)': reason=([^ ]+).*detail=(.*?) —", "[异常按钮]",
     lambda m: f"按钮「{m.group(1)}」触发 {m.group(2)}，已记录并跳过（{m.group(3)[:80]}）"),
    (r"review\[(\w{8})\]: wrong=(\[[^\]]*\])", "[质检]",
     lambda m: f"标注质检:{m.group(1)} 有画错的框 {m.group(2)}"),
    # [2026-07-09 用户] VLM 访问超时 / 重试 / 彻底失败,以及自愈重定位 —— 之前监视器
    # 完全不显示这些,遍历"卡住"时看不出是在等超时。现补全。
    (r"predict_mm: VLM call failed \(attempt (\d+)/(\d+)\): (.+)", "[超时]",
     lambda m: f"⏱ 模型访问失败,重试中 {m.group(1)}/{m.group(2)}　（{m.group(3).strip()[:60]}）"),
    (r"predict_mm: VLM call failed after (\d+) attempts; returning safe default", "[失败]",
     lambda m: f"✖ 模型访问{m.group(1)}次全失败 → 返回空结果(本次感知作废)"),
    (r"VLM grounding empty/failed; retrying \((\d+)/(\d+)\)", "[重试]",
     lambda m: f"↻ 元素识别为空,重新识别 {m.group(1)}/{m.group(2)}"),
    (r"VLM grounding still empty after (\d+) attempts", "[失败]",
     lambda m: f"✖ 元素识别{m.group(1)}次仍为空 → 本帧放弃(grounding 模式不退回 YOLO)"),
    (r"review self-heal \(modal\): wrong boxes (\d+) -> (\d+) via re-ground \((\d+)", "[自愈]",
     lambda m: f"模态弹窗自愈:错框 {m.group(1)}→{m.group(2)} 个(重新 grounding {m.group(3)} 次)"),
    (r"visual traversal done: (\d+) states, (\d+) actions", "[完成]",
     lambda m: f"遍历结束:{m.group(1)} 个页面 / {m.group(2)} 个动作"),
    (r"BFS frontier empty", "[完成]", lambda m: "前沿队列空 → 遍历完成"),
    # [2026-07-09 用户] 定点测试脚本(test_modal_region.py)直接发已带中文标签的行,
    # 形如 "... : [模态]  正文" —— 原样透传标签+正文,让调试台显示测试进度/结论。
    (r"(\[(?:取帧|前检|模态|区块|滚动|遍历|证据|校验|汇总|通过|失败)\])\s+(.*)", None,
     lambda m: (m.group(1), m.group(2).rstrip())),
]
COMPILED = [(re.compile(p), tag, f) for p, tag, f in RULES]

# [2026-07-09 用户] 把裸 state_id 翻成页面名。页面名来源:引擎的"新页注册"行
# (registered NEW visual state <id> 页面「名」)。监视器边读边建 id(8位)→名 的表,
# 再把所有引用 id 的行(重访/路由/返回/目标/串页…)里的裸 id 换成「名」id。
_NEWPAGE_RE = re.compile(r"registered NEW visual state (\w{8})\w* 页面「([^」]*)」")
# 8 位十六进制 id;负向后瞻跳过已带「」的 id(如新页行自身),避免「名」「名」id 重复包裹。
_ID_RE = re.compile(r"(?<!」)\b([0-9a-f]{8})\b")


def learn_page_name(line, id2name):
    """从一行日志里学 id→页面名(命中"新页注册"行时);其余行无副作用。"""
    m = _NEWPAGE_RE.search(line)
    if m and m.group(2).strip():
        id2name[m.group(1)] = m.group(2).strip()


def apply_names(msg, id2name):
    """把 msg 里所有【已知】的 8 位 id 替换成「页面名」id;未知的原样保留。"""
    if not id2name:
        return msg
    return _ID_RE.sub(lambda m: (f"「{id2name[m.group(1)]}」{m.group(1)}"
                                 if m.group(1) in id2name else m.group(1)), msg)


def translate(line):
    for rx, tag, fn in COMPILED:
        m = rx.search(line)
        if m:
            try:
                out = fn(m)
            except Exception:
                return tag, line.strip()[:100]
            # tag=None:透传规则,fn 返回 (动态tag, 正文) 元组
            if tag is None and isinstance(out, tuple) and len(out) == 2:
                return out
            return tag, out
    return None


def pick_log():
    logs = sorted(glob.glob("_scratch/*.log"), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


_PROGRESS_RE = re.compile(
    r"\[进度\] 节点 (\d+)\((\d+)待探\) · 区块 (\d+) · "
    r"导航按钮 (\d+)/(\d+)已探\((\d+)%\)"
)
_GRAPH_DIR_RE = re.compile(r"graph output -> (.+?)\s*$")
_TRAVERSAL_DONE_RE = re.compile(
    r"visual traversal done: (\d+) states, (\d+) actions \(stop=([^)]+)\)"
)
_CLICK_RE = re.compile(r"explorer: click '([^']+)'")
_PAGE_RE = re.compile(
    r"registered NEW visual state \w+ 页面「([^」]*)」"
)


class RunSummary:
    """Deterministic end-of-run summary built from the log and graph.json."""

    def __init__(self, log_path, graph_path=None):
        self.log_path = os.path.abspath(log_path)
        self.graph_path = os.path.abspath(graph_path) if graph_path else None
        self.progress = None
        self.last_click = ""
        self.pages = []
        self.off_app = 0
        self.off_app_by_click = Counter()
        self.router_hard_resets = 0
        self.quarantined_clicks = 0
        self.quarantined_edges = 0
        self.vlm_failures = 0
        self.perception_failures = 0
        self.abnormal_button_events = Counter()
        self.logged_errors = 0
        self.done_states = None
        self.done_actions = None
        self.stop_reason = ""
        self.env_closed = False

    def observe(self, line):
        match = _GRAPH_DIR_RE.search(line)
        if match:
            directory = match.group(1).strip().strip('"')
            self.graph_path = os.path.join(directory, "graph.json")
        match = _PROGRESS_RE.search(line)
        if match:
            self.progress = tuple(int(value) for value in match.groups())
        match = _TRAVERSAL_DONE_RE.search(line)
        if match:
            self.done_states = int(match.group(1))
            self.done_actions = int(match.group(2))
            self.stop_reason = match.group(3).strip()
        match = _CLICK_RE.search(line)
        if match:
            self.last_click = match.group(1).strip()
        match = _PAGE_RE.search(line)
        if match and match.group(1).strip():
            page = match.group(1).strip()
            if page not in self.pages:
                self.pages.append(page)

        if "focus guard: off-app detected" in line:
            self.off_app += 1
            if self.last_click:
                self.off_app_by_click[self.last_click] += 1
        if "router:" in line and "hard reset" in line.lower():
            self.router_hard_resets += 1
        if "QUARANTINE navigation click" in line:
            self.quarantined_clicks += 1
        if "QUARANTINE edge" in line:
            self.quarantined_edges += 1
        if "predict_mm: VLM call failed" in line \
                or "VLM grounding still empty" in line:
            self.vlm_failures += 1
        if "perception unavailable" in line.lower():
            self.perception_failures += 1
        match = re.search(r"ABNORMAL BUTTON '([^']+)': reason=([^ ]+)", line)
        if match:
            self.abnormal_button_events[(match.group(1), match.group(2))] += 1
        if " ERROR " in line:
            self.logged_errors += 1
        if "env closed (container/VM released)" in line:
            self.env_closed = True

    def _read_graph(self):
        path = self.graph_path
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except Exception:
            return None
        nodes = data.get("nodes", []) or []
        edges = data.get("edges", data.get("links", [])) or []
        pages = []
        for node in nodes:
            name = str(node.get("page_name", "") or "").strip()
            if name and name not in pages:
                pages.append(name)
        try:
            from gui_rewalk.src.core.graph.traversal_completion import (
                evaluate_traversal_completion,
            )
            certificate = evaluate_traversal_completion(data)
            completion_status = str(
                certificate.get("status") or "incomplete")
            failed_checks = [
                check_id for check_id, check in
                certificate.get("checks", {}).items()
                if check.get("passed") is not True
            ]
        except Exception:
            completion_status = "unavailable"
            failed_checks = ["certificate_unavailable"]
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "actions": int(data.get("action_counter", 0) or 0),
            "stop_reason": str(data.get("stop_reason", "") or ""),
            "pages": pages,
            "abnormal_buttons": list(data.get("abnormal_buttons", []) or []),
            "completion_status": completion_status,
            "completion_failed_checks": failed_checks,
        }

    @staticmethod
    def _reason_text(reason):
        return {
            "frontier_empty": "全部可探索候选已处理（frontier_empty）",
            "max_actions": "达到动作安全上限，可继续 resume",
            "max_states": "达到节点安全上限，可继续 resume",
            "perception_unavailable": "关键页面感知不可用，已保存最后好图",
            "off_app": "目标应用无法恢复到前台",
            "backtrack_failures": "回溯连续失败",
        }.get(reason, reason or "进程退出但未记录明确停止原因")

    def render(self):
        graph = self._read_graph()
        nodes = (graph or {}).get("nodes", self.done_states)
        edges = (graph or {}).get("edges")
        actions = (graph or {}).get("actions", self.done_actions)
        # A completed log line belongs to this supervised run and is authoritative.
        # A loaded graph may retain an older stop_reason until the run finishes.
        reason = self.stop_reason or "process_exited_without_final_status"
        complete = (graph or {}).get("completion_status") == "certified"
        headline = "遍历已完成" if complete else "遍历已停止"
        counts = []
        if nodes is not None:
            counts.append(f"{nodes} 个节点")
        if edges is not None:
            counts.append(f"{edges} 条实测边")
        if actions is not None:
            counts.append(f"{actions} 个已提交动作")

        lines = ["", "═" * 58, f"{headline}：" + "，".join(counts)]
        if self.progress:
            _n, pending, regions, explored, total, percent = self.progress
            lines.append(
                f"图概况：{regions} 个区块；导航覆盖 {explored}/{total} "
                f"({percent}%)；仍有候选的节点 {pending} 个"
            )
        pages = (graph or {}).get("pages") or self.pages
        if pages:
            shown = "、".join(pages[-6:])
            prefix = "…、" if len(pages) > 6 else ""
            lines.append(f"页面示例：{prefix}{shown}")
        lines.append(f"停止原因：{self._reason_text(reason)}")

        issues = []
        if graph and graph.get("completion_status") != "certified":
            failed = graph.get("completion_failed_checks") or []
            issues.append(
                "完整性认证未通过: " + (", ".join(failed) or "unknown"))
        if self.off_app:
            detail = ""
            if self.off_app_by_click:
                detail = "；" + "、".join(
                    f"{name}×{count}"
                    for name, count in self.off_app_by_click.most_common(3)
                )
            issues.append(f"离开应用/闪退 {self.off_app} 次{detail}")
        if self.router_hard_resets:
            issues.append(f"Router hard reset {self.router_hard_resets} 次")
        if self.quarantined_clicks or self.quarantined_edges:
            issues.append(
                f"隔离点击 {self.quarantined_clicks} 次、可疑边 "
                f"{self.quarantined_edges} 条"
            )
        if self.vlm_failures:
            issues.append(f"VLM/grounding 失败或重试 {self.vlm_failures} 次")
        if self.perception_failures:
            issues.append(f"关键感知不可用 {self.perception_failures} 次")
        abnormal = (graph or {}).get("abnormal_buttons") or []
        if abnormal:
            labels = "、".join(
                f"{item.get('element_name') or '(未命名)'}:{item.get('reason') or 'unknown'}"
                for item in abnormal[:5]
            )
            issues.append(f"异常按钮 {len(abnormal)} 个（{labels}）")
        elif self.abnormal_button_events:
            labels = "、".join(
                f"{name}:{reason}"
                for (name, reason), _count
                in self.abnormal_button_events.most_common(5)
            )
            issues.append(f"异常按钮（{labels}）")
        if not complete and reason != "process_exited_without_final_status":
            issues.append("遍历尚未达到 frontier_empty")
        if reason == "process_exited_without_final_status":
            issues.append("进程未输出正常结束记录，需检查末尾日志")
        lines.append("问题判断：" + ("；".join(issues) if issues else "未发现明显异常"))
        if self.graph_path:
            lines.append(f"图文件：{self.graph_path}")
        lines.append("═" * 58)
        return "\n".join(lines)


def _pid_alive(pid):
    """Cross-platform liveness check without adding a psutil dependency."""
    if not pid:
        return None
    if os.name == "nt":
        process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GUI traversal live status monitor")
    parser.add_argument("log_path", nargs="?", default=None)
    parser.add_argument("--pid", type=int, default=None,
                        help="supervised traversal PID; enables reliable end summary")
    parser.add_argument("--graph", default=None,
                        help="optional graph.json path; normally learned from the log")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    path = args.log_path or pick_log()
    if not path or not os.path.exists(path):
        print("找不到日志。用法: python tools/live_status.py <日志路径>")
        return
    print(f"═══ 实时状态监视器 ═══  跟随: {path}")
    print("(Ctrl+C 退出)\n")
    id2name = {}
    summary = RunSummary(path, graph_path=args.graph)
    # 预扫全文建 id→名 表:监视器从末尾跟随,启动前注册过的页面否则查不到名。
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f0:
            for line in f0:
                learn_page_name(line, id2name)
                summary.observe(line)
    except Exception:
        pass
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)          # 从末尾开始跟随
        node = 0
        dead_checks = 0
        terminal_seen_at = None
        while True:
            line = f.readline()
            if not line:
                if summary.env_closed and terminal_seen_at is None:
                    terminal_seen_at = time.monotonic()
                alive = _pid_alive(args.pid)
                if alive is False:
                    dead_checks += 1
                else:
                    dead_checks = 0
                # With a PID, require two dead observations.  Without one, retain
                # compatibility and finish only after the explicit env-close line.
                ended = dead_checks >= 2 or (
                    args.pid is None and terminal_seen_at is not None
                    and time.monotonic() - terminal_seen_at >= 1.2
                )
                if ended:
                    print(summary.render(), flush=True)
                    return
                time.sleep(0.4)
                continue
            summary.observe(line)
            learn_page_name(line, id2name)   # 跟随中新注册的页面继续入表
            r = translate(line)
            if r:
                tag, msg = r
                if tag == "[新页]" and "注册【新页面】" in msg:
                    node += 1
                    msg = f"{msg}  ← 第 {node} 个页面"
                msg = apply_names(msg, id2name)   # 裸 id → 「页面名」id
                ts = line[11:19] if len(line) > 19 and line[13:14] == ":" else time.strftime("%H:%M:%S")
                print(f"[{ts}] {tag}  {msg}", flush=True)


if __name__ == "__main__":
    main()
