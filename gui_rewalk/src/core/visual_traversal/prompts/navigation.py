"""Navigation and safety prompt catalog for visual traversal."""


INTERRUPTION_DISMISS_PROMPT = (
    "判断当前前景界面是否是临时打断层，以及候选是否会直接关闭该层并返回被打断的"
    "界面。\n"
    "只有同时确认这两点时才允许 click。会继续当前流程、接受其后果、进入其他功能，"
    "或者本身不是可操作控件的候选，都不是关闭动作。\n"
    "画面上探测到的可点元素(编号 + 名字 + 用途 + 预期即时效果):\n{candidates}\n\n"
    "一次只判断并关闭当前最前层。若不存在临时打断层、没有能直接关闭它的候选，"
    "或者因果结果不确定，返回 done。\n"
    "只输出 JSON:{{\"action\": \"click\" 或 \"done\", "
    "\"surface_is_temporary\": true 或 false, "
    "\"target_is_close_control\": true 或 false, "
    "\"button_id\": <要点的元素编号, action=click 时必填>, \"reason\": \"一句话\"}}。\n"
    "action=click 只有在 surface_is_temporary=true 且 target_is_close_control=true 时有效；"
    "不确定时两个字段都填 false 并返回 done。"
)

STATEFUL_RISK_PROMPT = (
    "You are the independent safety gate for a GUI exploration agent. The screenshot "
    "shows the full current application page. The upstream perception model proposed "
    "clicking this reversible state control:\n{element}\n\n"
    "Do not trust the upstream risk label and do not decide from the control's name alone. "
    "Judge its causal consequences together with the page, nearby title, and current "
    "execution environment. DENY if changing it can disrupt any transport/control channel "
    "used by the automation, terminate or suspend the session/application/device, mutate "
    "or destroy user data, cross an authentication/permission/security boundary, commit an "
    "irreversible external effect, or if the consequence is uncertain. ALLOW only when the "
    "visible evidence establishes that it is a local reversible feature gate whose change "
    "can be observed and inverted without affecting those boundaries. Fail closed. Output "
    "JSON only: "
    "{\"allow\":true/false,\"risk\":\"none|connectivity|destructive|authentication|"
    "permission|unknown\",\"reason\":\"one concise sentence\"}"
)

def build_return_path_prompt(source_name, target_name, transition, *,
                             platform: str = "desktop") -> str:
    """Ask for one visible or platform action that may return image 2 to image 1."""
    platform_action = (
        '{"action_type":"navigate_back"}'
        if str(platform or "").strip().casefold() == "android"
        else '{"action_type":"PRESS","parameters":{"key":"esc"}}'
    )
    return "\n".join([
        "你是一名 GUI 反向动作探索助手。",
        "图1是刚才执行操作前的完整界面，图2是执行操作后的当前完整界面。",
        f"图1界面：{source_name or '未知'}。",
        f"图2界面：{target_name or '未知'}。",
        f"刚才执行的可见入口：{transition or '未知'}。",
        f"当前平台：{platform or 'desktop'}。",
        "",
        "这不是要求一定返回的任务。",
        "先判断图2是否应当继续作为当前操作界面遍历。",
        "若图2是刚才入口正常产生、仍实际接收操作的界面，输出："
        '{"action":null}；不要仅为了建立或验证返回路径而离开图2。',
        "只有图2不应继续遍历、且必须立即恢复图1时，才选择一个原子动作尝试直接返回。",
        "若图2中存在明确对应图1的可见入口，优先点击该可见入口。",
        "可见点击输出："
        '{"action":{"action_type":"CLICK","target":"图2中的自然语言可见目标"}}。',
        "只有没有合适的可见入口时，才可以选择当前平台的返回动作："
        f'{{"action":{platform_action}}}。',
        "如果不能确认必须立即返回，或者动作可能提交、破坏已有状态、产生不可逆影响，"
        "或者无法可靠判断，"
        '输出：{"action":null}。',
        "",
        "不要输出坐标、候选编号、Page ID、Region ID 或其他框架内部字段。",
        "不要判断动作是否成功；真实落点会在执行后另行验证。",
        "只输出一个 JSON 对象，不要输出解释文字。",
    ])


__all__ = [
    "INTERRUPTION_DISMISS_PROMPT",
    "STATEFUL_RISK_PROMPT",
    "build_return_path_prompt",
]
