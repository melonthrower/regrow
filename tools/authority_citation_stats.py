from __future__ import annotations

from pathlib import Path
import json
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = REPO_ROOT / "research" / "paper" / "generated"
INTRO_SOURCES = [
    GENERATED_DIR / "gui_related_intro_extractions.json",
    GENERATED_DIR / "mineru_recent_dataset_intro_extractions.json",
]

OUT = GENERATED_DIR / "authority_citation_stats.md"


ALIASES = {
    "Mind2Web": ["Mind2Web"],
    "WebArena": ["WebArena"],
    "VisualWebArena": ["VisualWebArena", "Visual WebArena"],
    "WebShop": ["WebShop"],
    "MiniWoB++": ["MiniWoB++", "MiniWoB"],
    "WebVoyager": ["WebVoyager"],
    "SeeClick": ["SeeClick"],
    "ScreenSpot": ["ScreenSpot", "Screen Spot"],
    "OSWorld": ["OSWorld"],
    "WorkArena": ["WorkArena"],
    "Android in the Wild / AITW": ["Android in the Wild", "AITW"],
    "AndroidControl": ["AndroidControl", "Android Control"],
    "AndroidWorld": ["AndroidWorld", "Android World"],
    "AndroidLab": ["AndroidLab", "Android Lab"],
    "Mobile-Agent": ["Mobile-Agent", "MobileAgent"],
    "AppAgent": ["AppAgent", "App Agent"],
    "AutoDroid": ["AutoDroid"],
    "WebLINX": ["WebLINX"],
    "OmniACT": ["OmniACT"],
    "CogAgent": ["CogAgent"],
    "Ferret-UI": ["Ferret-UI", "FerretUI"],
    "UI-TARS": ["UI-TARS", "UITARS"],
    "OS-ATLAS": ["OS-ATLAS", "OS ATLAS"],
    "OpenCUA": ["OpenCUA", "Open CUA"],
    "VideoGUI": ["VideoGUI"],
    "TongUI": ["TongUI"],
    "GUI-Odyssey": ["GUI-Odyssey", "GUIOdyssey", "GUI Odyssey"],
    "Explorer": ["Explorer"],
    "GUI-explorer": ["GUI-explorer", "GUI Explorer"],
    "OS-Genesis": ["OS-Genesis", "OS Genesis"],
    "UI-E2I-Synth": ["UI-E2I-Synth", "UI E2I Synth"],
    "Video2GUI": ["Video2GUI"],
    "WebForge": ["WebForge"],
    "MobileGym": ["MobileGym", "MOBILEGYM"],
    "SimuWoB": ["SimuWoB", "ScaleWoB"],
    "AndroidDaily": ["AndroidDaily"],
    "WindowsWorld": ["WindowsWorld"],
    "Odysseys": ["Odysseys"],
    "MolmoWeb": ["MolmoWeb"],
    "Workflow-GYM": ["Workflow-GYM", "Workflow GYM"],
    "Rico": ["Rico"],
    "Screen2Words": ["Screen2Words", "Screen to Words"],
    "Widget Captioning": ["Widget Captioning"],
    "WebSRC": ["WebSRC"],
    "AgentBench": ["AgentBench"],
}

GROUPS = {
    "经典 web agent / web benchmark": [
        "MiniWoB++",
        "WebShop",
        "Mind2Web",
        "WebArena",
        "VisualWebArena",
        "WebVoyager",
        "WebLINX",
    ],
    "经典 mobile / desktop GUI benchmark": [
        "Android in the Wild / AITW",
        "AndroidControl",
        "AndroidWorld",
        "AndroidLab",
        "OSWorld",
        "WorkArena",
        "WindowsWorld",
    ],
    "GUI grounding / perception": [
        "SeeClick",
        "ScreenSpot",
        "Ferret-UI",
        "CogAgent",
        "OmniACT",
        "UI-E2I-Synth",
        "AutoGUI_v2",
    ],
    "GUI agent model / open foundation": [
        "Mobile-Agent",
        "AppAgent",
        "AutoDroid",
        "UI-TARS",
        "OS-ATLAS",
        "OpenCUA",
        "MolmoWeb",
    ],
    "数据生成 / 轨迹合成 / 探索": [
        "VideoGUI",
        "TongUI",
        "Explorer",
        "GUI-explorer",
        "OS-Genesis",
        "Video2GUI",
        "WebForge",
        "MobileGym",
        "SimuWoB",
        "AndroidDaily",
    ],
}


def load_items() -> list[dict]:
    items = []
    for source in INTRO_SOURCES:
        if not source.is_file():
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        for item in data:
            intro = item.get("intro", "")
            if not intro:
                continue
            label = item.get("paper") or item.get("file") or item.get("title") or str(source)
            items.append({"label": label, "intro": intro})
    return items


def count_alias(text: str, aliases: list[str]) -> int:
    count = 0
    for alias in aliases:
        pattern = r"(?i)(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        count += len(re.findall(pattern, text))
    return count


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    items = load_items()
    rows = []
    for name, aliases in ALIASES.items():
        paper_hits = []
        total = 0
        for item in items:
            hit = count_alias(item["intro"], aliases)
            if hit:
                paper_hits.append(item["label"])
                total += hit
        rows.append(
            {
                "name": name,
                "total_mentions": total,
                "intro_papers": len(set(paper_hits)),
                "examples": sorted(set(paper_hits))[:8],
            }
        )
    rows.sort(key=lambda row: (row["intro_papers"], row["total_mentions"], row["name"]), reverse=True)

    lines = []
    lines.append("# 权威引用统计：GUI Agent Introduction 语料中的高频工作\n")
    lines.append(f"统计语料：{len(items)} 篇论文的 Introduction；来源包括本地 related works 粗抽和近几个月 MinerU 精抽。\n")
    lines.append("> 说明：这里统计的是 Introduction 中显式出现的数据集/benchmark/方法名，不等同于 Google Scholar 引用数；它更接近“近期 GUI agent 论文写 introduction 时默认会提到谁”。\n")
    lines.append("| 工作 | 出现于多少篇 intro | 总提及次数 | 出现示例 |\n")
    lines.append("|---|---:|---:|---|\n")
    for row in rows:
        if row["intro_papers"] == 0:
            continue
        examples = "; ".join(row["examples"][:4])
        lines.append(f"| {row['name']} | {row['intro_papers']} | {row['total_mentions']} | {examples} |\n")

    lines.append("\n## 按写作用途分组\n")
    for group, names in GROUPS.items():
        lines.append(f"\n### {group}\n")
        group_rows = [row for row in rows if row["name"] in names and row["intro_papers"] > 0]
        group_rows.sort(key=lambda row: (row["intro_papers"], row["total_mentions"]), reverse=True)
        for row in group_rows:
            lines.append(f"- **{row['name']}**：{row['intro_papers']} 篇 intro 出现，{row['total_mentions']} 次提及。\n")

    lines.append("\n## 对我们论文 introduction 的建议引用组合\n")
    lines.append("\n第一段背景建议引用：Mind2Web, WebArena, VisualWebArena, OSWorld, Android in the Wild / AndroidControl。\n")
    lines.append("数据瓶颈建议引用：AndroidControl, OpenCUA, VideoGUI, TongUI, Video2GUI。\n")
    lines.append("探索/合成任务建议引用：Explorer, GUI-explorer, OS-Genesis, WebForge, MobileGym, SimuWoB。\n")
    lines.append("GUI grounding 建议引用：SeeClick, ScreenSpot, Ferret-UI, UI-E2I-Synth。\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"items={len(items)}")
    print(f"out={OUT}")
    for row in rows[:20]:
        print(row["name"], row["intro_papers"], row["total_mentions"])


if __name__ == "__main__":
    main()
