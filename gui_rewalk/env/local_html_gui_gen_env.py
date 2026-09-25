"""Headless Chromium environment for repository-owned HTML fixtures.

This adapter normally exposes only the screenshot/action surface consumed by the
visual traversal engine.  An explicit fixture-only experiment may additionally
resolve a stored semantic target against repository-owned ``data-action-id`` and
embedded oracle metadata.  That opt-in path is isolated from normal perception,
identity, routing, and completion behavior.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


_KEY_NAMES = {
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "tab": "Tab",
    "space": " ",
    "home": "Home",
    "end": "End",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
}


class LocalHTMLController:
    """Translate the framework's generic action dictionaries to Playwright."""

    def __init__(self, page: Page, screen_size: Tuple[int, int], start_url: str):
        self.page = page
        self.screen_size = screen_size
        self.start_url = start_url

    def get_screenshot(self) -> bytes:
        return self.page.screenshot(type="png", full_page=False)

    def get_terminal_output(self):
        return None

    def get_vm_platform(self) -> str:
        return "local_html"

    def get_vm_screen_size(self) -> Tuple[int, int]:
        return self.screen_size

    @staticmethod
    def _params(action: Dict[str, Any]) -> Dict[str, Any]:
        return action.get("parameters") or {
            key: value for key, value in action.items() if key != "action_type"
        }

    @staticmethod
    def _key(value: Any) -> str:
        text = str(value or "").strip()
        return _KEY_NAMES.get(text.lower(), text)

    def execute_gui_action(self, action: Dict[str, Any]):
        native_type = str(action.get("action_type", "")).strip().casefold()
        native_aliases = {
            "click": "CLICK",
            "double_tap": "DOUBLE_CLICK",
            "input_text": "TYPE",
            "keyboard_enter": "PRESS",
            "long_press": "LONG_PRESS",
            "navigate_back": "BACK",
            "navigate_home": "HOME",
            "swipe": "SWIPE",
            "wait": "WAIT",
        }
        action_type = native_aliases.get(
            native_type, str(action.get("action_type", "")).upper())
        params = self._params(action)
        if native_type == "keyboard_enter":
            params = {**params, "key": "enter"}
        if action_type in {"WAIT", "FAIL", "FINISHED", "DONE", "MOVE_TO"}:
            return
        if action_type == "CLICK":
            self.page.mouse.click(
                float(params["x"]), float(params["y"]),
                button=str(params.get("button", "left")),
                click_count=int(params.get("num_clicks", 1)),
            )
            return
        if action_type == "DOUBLE_CLICK":
            self.page.mouse.dblclick(float(params["x"]), float(params["y"]))
            return
        if action_type in {"RIGHT_CLICK", "RIGHT_SINGLE"}:
            self.page.mouse.click(
                float(params["x"]), float(params["y"]), button="right")
            return
        if action_type == "LONG_PRESS":
            self.page.mouse.move(float(params["x"]), float(params["y"]))
            self.page.mouse.down()
            self.page.wait_for_timeout(650)
            self.page.mouse.up()
            return
        if action_type == "TYPE":
            if params.get("x") is not None and params.get("y") is not None:
                self.page.mouse.click(float(params["x"]), float(params["y"]))
            self.page.keyboard.insert_text(str(params.get("text", "")))
            return
        if action_type == "PRESS":
            self.page.keyboard.press(self._key(params.get("key", "")))
            return
        if action_type == "HOTKEY":
            keys = [self._key(key) for key in params.get("keys", [])]
            if keys:
                self.page.keyboard.press("+".join(keys))
            return
        if action_type == "SCROLL":
            self._scroll(params)
            return
        if action_type == "SWIPE":
            width, height = self.screen_size
            margin_x, margin_y = max(1, width // 12), max(1, height // 12)
            cx, cy = width // 2, height // 2
            endpoints = {
                "down": ((cx, margin_y), (cx, height - margin_y)),
                "up": ((cx, height - margin_y), (cx, margin_y)),
                "right": ((margin_x, cy), (width - margin_x, cy)),
                "left": ((width - margin_x, cy), (margin_x, cy)),
            }
            direction = str(params.get("direction") or "").casefold()
            if direction not in endpoints:
                raise ValueError(
                    f"Invalid AndroidWorld swipe direction: {direction}")
            (x1, y1), (x2, y2) = endpoints[direction]
            self.page.mouse.move(x1, y1)
            self.page.mouse.down()
            self.page.mouse.move(x2, y2, steps=10)
            self.page.mouse.up()
            return
        if action_type in {"DRAG", "DRAG_TO"}:
            x1 = float(params.get("x1", params.get("start_x", self.screen_size[0] / 2)))
            y1 = float(params.get("y1", params.get("start_y", self.screen_size[1] / 2)))
            x2 = float(params.get("x2", params.get("x", x1)))
            y2 = float(params.get("y2", params.get("y", y1)))
            self.page.mouse.move(x1, y1)
            self.page.mouse.down()
            self.page.mouse.move(x2, y2, steps=10)
            self.page.mouse.up()
            return
        if action_type == "BACK":
            self.page.go_back(wait_until="domcontentloaded")
            return
        if action_type == "HOME":
            self.page.goto(self.start_url, wait_until="domcontentloaded")
            return
        if action_type in {"MOUSE_DOWN", "MOUSE_UP", "KEY_DOWN", "KEY_UP"}:
            return
        raise ValueError(f"Unsupported local_html action type: {action_type}")

    execute_action = execute_gui_action

    def _scroll(self, params: Dict[str, Any]) -> None:
        width, height = self.screen_size
        x = float(params.get("x", width / 2))
        y = float(params.get("y", height / 2))
        self.page.mouse.move(x, y)
        direction = str(params.get("direction", "") or "").lower()
        amount = max(1, int(params.get("amount", 1) or 1))
        frac = float(params.get("frac", 0.67) or 0.67)
        span_y = max(120, int(height * min(1.0, max(0.15, frac))))
        span_x = max(80, int(width * min(1.0, max(0.15, frac))))
        if direction == "down":
            dx, dy = 0, span_y * amount
        elif direction == "up":
            dx, dy = 0, -span_y * amount
        elif direction == "right":
            dx, dy = span_x * amount, 0
        elif direction == "left":
            dx, dy = -span_x * amount, 0
        else:
            # Framework desktop dx/dy values are pyautogui wheel *clicks*, not
            # browser pixels.  Playwright expects pixel deltas; without this
            # conversion the canonical eight-click traversal step moved only
            # eight pixels and the viewport pHash incorrectly called long pages
            # static.  Keep the pyautogui sign convention (positive is up).
            wheel_px = 100
            dx = -int(params.get("dx", 0) or 0) * wheel_px
            dy = -int(params.get("dy", 0) or 0) * wheel_px
        self.page.mouse.wheel(dx, dy)


class LocalHTMLGUIGenEnv:
    """Minimal visual environment backed by one headless Chromium page."""

    platform = "local_html"
    provider_name = "local_html"

    def __init__(
        self,
        html_path: str,
        action_space: str = "gen_data",
        screen_size: Tuple[int, int] = (412, 915),
        clean_start: bool = False,
        start_hash: str = "#/inbox",
        fixture_oracle_inventory: bool = False,
        fixture_oracle_grounding: bool = False,
        platform_kind: str = "",
    ):
        asset = Path(html_path).expanduser().resolve()
        if not asset.is_file():
            raise FileNotFoundError(f"local_html asset does not exist: {asset}")
        start_hash = str(start_hash or "")
        if (
            not start_hash.startswith("#/")
            or len(start_hash) <= 2
            or start_hash != start_hash.strip()
            or any(char.isspace() for char in start_hash)
            or "#" in start_hash[1:]
        ):
            raise ValueError(
                "local_html start_hash must use format '#/<route>' without "
                f"whitespace or a second '#'; got {start_hash!r}")
        self.path_to_vm = str(asset)
        self.action_space = action_space
        self.screen_size = tuple(int(value) for value in screen_size)
        self.clean_start = bool(clean_start)
        self.fixture_oracle_inventory = bool(fixture_oracle_inventory)
        self.fixture_oracle_grounding = bool(fixture_oracle_grounding)
        self.platform_kind = (
            str(platform_kind or "").strip().casefold()
            or ("android" if self.screen_size[0] <= 600 else "local_html"))
        self.start_hash = start_hash
        self.start_url = asset.as_uri() + start_hash
        self.is_environment_used = False
        self.action_history = []
        self._step_no = 0
        self._playwright: Optional[Playwright] = sync_playwright().start()
        self._browser: Optional[Browser] = self._playwright.chromium.launch(headless=True)
        self._context: Optional[BrowserContext] = self._browser.new_context(
            viewport={"width": self.screen_size[0], "height": self.screen_size[1]},
            device_scale_factor=1,
            is_mobile=self.platform_kind == "android",
            has_touch=self.platform_kind == "android",
        )
        self._page: Optional[Page] = self._context.new_page()
        self.controller = LocalHTMLController(
            self._page, self.screen_size, self.start_url)

    def fixture_semantic_inventory(
        self, *, full_surface: bool = False,
    ) -> Dict[str, Any]:
        """Return exact fixture blocks/elements for diagnostics.

        The default remains current-viewport only. ``full_surface=True`` is used
        only after a real scroll sweep has reached the bottom; it lets the
        fixture-oracle path inventory the already captured full-page surface
        instead of silently re-reading the restored top viewport.
        """
        if not self.fixture_oracle_inventory:
            return {}
        return dict(self._page.evaluate(
            """(fullSurface) => {
              const oracleNode = document.getElementById("fixture-oracle");
              if (!oracleNode) return {};
              const oracle = JSON.parse(oracleNode.textContent);
              const snapshot = window.__mingle?.snapshot?.() || {};
              const pageId = snapshot.page || document.querySelector("[data-page-id]")?.dataset.pageId || "";
              const page = (oracle.pages || []).find(row => row.id === pageId);
              if (!page) return {};
              const surfaceNode = document.querySelector("[data-surface-id]");
              const surfaceId = surfaceNode?.dataset.surfaceId || "";
              const surface = (oracle.surfaces || []).find(row => row.id === surfaceId);
              const activeRoot = surfaceNode || document.querySelector(`[data-page-id="${pageId}"]`);
              if (!activeRoot) return {};
              const visible = node => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden"
                  && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0
                  && rect.right > 0 && rect.left < innerWidth
                  && (fullSurface || (rect.bottom > 0 && rect.top < innerHeight));
              };
              const controlRows = surface ? (surface.controls || []) : (page.controls || []);
              const controls = new Map(controlRows.map(row => [row.id, row]));
              const blockRows = surface
                ? [{id: surface.id, role: surface.kind, scrollable: false}]
                : (page.blocks || []);
              const blockBox = id => {
                const matches = [...activeRoot.querySelectorAll(`[data-block-id="${id}"]`)]
                  .filter(visible);
                const containers = matches.filter(node => !node.hasAttribute("data-action-id"));
                const nodes = containers.length ? containers : matches;
                if (!nodes.length) return null;
                const rects = nodes.map(node => node.getBoundingClientRect());
                const left = Math.max(0, Math.min(...rects.map(rect => rect.left)));
                const top = Math.max(0, Math.min(...rects.map(rect => rect.top)));
                const right = Math.min(innerWidth, Math.max(...rects.map(rect => rect.right)));
                const bottom = Math.min(innerHeight, Math.max(...rects.map(rect => rect.bottom)));
                if (!(left < right && top < bottom)) return null;
                return [left, top, right, bottom].map((value, index) => Math.round(
                  value / (index % 2 === 0 ? innerWidth : innerHeight) * 1000));
              };
              const blocks = new Map(blockRows.map(row => [row.id, {
                role: row.role, note: `Fixture ${row.role}`,
                scrollable: Boolean(row.scrollable), fixture_oracle: true,
                bbox_1000: blockBox(row.id),
                elements: [],
              }]));
              const typeOf = node => {
                if (node.matches("input,textarea")) return "textbox";
                if (node.classList.contains("switch-button")) return "switch";
                if (node.classList.contains("nav-button")) return "tab";
                if (node.classList.contains("icon-button")) return "icon_button";
                if (node.classList.contains("chat-row") || node.classList.contains("contact-row")
                    || node.classList.contains("menu-row")) return "list_item";
                return "button";
              };
              const labelOf = node => {
                const explicit = node.getAttribute("aria-label")
                  || node.getAttribute("placeholder");
                if (explicit) return explicit.trim();
                const text = (node.innerText || "").trim();
                if (node.classList.contains("nav-button")) {
                  return text.split(/\\s+/).filter(Boolean).at(-1) || text;
                }
                return text;
              };
              const stateValue = (id, node) => {
                const keys = {
                  "inbox.search": "searchOpen",
                  "conversation.send": "messageSent",
                  "contact.favorite": "favorite",
                  "settings.notifications_toggle": "notifications",
                  "chat_info.mute": "muted",
                };
                const key = keys[id];
                if (key && typeof snapshot.state?.[key] === "boolean") {
                  return snapshot.state[key] ? "on" : "off";
                }
                const pressed = node.getAttribute("aria-pressed");
                return pressed === "true" ? "on" : pressed === "false" ? "off" : "unknown";
              };
              for (const node of activeRoot.querySelectorAll("[data-action-id]")) {
                if (!visible(node)) continue;
                const id = node.dataset.actionId;
                const spec = controls.get(id);
                const selected = node.getAttribute("aria-current") === "page"
                  || node.getAttribute("aria-pressed") === "true";
                // The DOM contains deliberately disabled filler rows used to make
                // long pages realistic.  They are not part of the fixture oracle
                // and therefore must not become traversal candidates here.  The
                // active navigation item is the one exception: fixtures omit the
                // current tab from their action contract, but identity still needs
                // its selected state.  Frontier filtering consumes it as selected.
                if (!spec && !selected) continue;
                const blockId = surface ? surface.id : (node.dataset.blockId || "");
                if (!blocks.has(blockId)) continue;
                const rawCategory = spec?.category || "navigation";
                const stateful = rawCategory === "stateful";
                const blockedReason = spec?.blocked_reason || (node.disabled ? "fixture_disabled" : "");
                const rect = node.getBoundingClientRect();
                blocks.get(blockId).elements.push({
                  name: spec?.label || labelOf(node), type: spec?.type || typeOf(node),
                  interactive: true,
                  category: rawCategory === "dangerous" ? "dangerous"
                    : (stateful && spec?.reversible === true) ? "navigation"
                    : (stateful || rawCategory === "input") ? "shallow" : "navigation",
                  selected, group: spec?.group || "",
                  back: id.endsWith(".back") || id.endsWith(".close") || id === "clear.cancel",
                  enabled: spec?.enabled === false ? false : !node.disabled,
                  requires_permission: blockedReason.includes("permission"),
                  blocked_reason: blockedReason,
                  stateful,
                  state_key: stateful ? id : "",
                  state_value: stateful ? stateValue(id, node) : "unknown",
                  effect_scope: stateful ? (spec?.effect_scope || "unknown") : "unknown",
                  reversible: stateful ? spec?.reversible === true : null,
                  risk: spec?.risk || (rawCategory === "dangerous" ? "unknown" : "none"),
                  bbox_xywh: fullSurface
                    ? [rect.left, rect.top + scrollY, rect.width, rect.height]
                    : undefined,
                  identity_anchor: true,
                });
              }
              const anchors = surface ? (surface.anchors || [])
                : [page.title, ...(page.anchors || []), page.scroll?.bottom_anchor].filter(Boolean);
              for (const anchor of anchors) {
                const matches = [...activeRoot.querySelectorAll("*")]
                  .filter(node => visible(node) && (node.textContent || "").trim().includes(anchor))
                  .sort((left, right) => (left.textContent || "").length - (right.textContent || "").length);
                const node = matches[0];
                if (!node) continue;
                const blockId = surface ? surface.id
                  : (node.closest("[data-block-id]")?.dataset.blockId
                     || (page.blocks || [])[0]?.id || "");
                const block = blocks.get(blockId);
                if (!block || block.elements.some(element => element.name === anchor)) continue;
                block.elements.unshift({
                  name: anchor, type: anchor === page.title ? "heading" : "text",
                  interactive: false, category: "display", selected: false,
                  group: "", back: false, enabled: true,
                  requires_permission: false, blocked_reason: "", stateful: false,
                  state_key: "", state_value: "unknown", effect_scope: "unknown",
                  reversible: null, risk: "unknown", identity_anchor: true,
                });
              }
              return {
                page: page.title,
                surface_kind: surface?.kind || "page",
                surface_scrollable: surface ? Boolean(surface.scrollable)
                  : page.scroll?.classification === "scrollable",
                is_system_dialog: false, is_interruption: false,
                blocks: [...blocks.values()].filter(
                  block => block.elements.length || block.scrollable),
              };
            }""",
            bool(full_surface),
        ) or {})

    def autonomous_fixture_audit(
        self, action: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record fixture truth for post-run acceptance, never model input."""
        params = LocalHTMLController._params(action or {})
        action_type = str((action or {}).get("action_type") or "").casefold()
        point = None
        if action_type in {"click", "double_click", "right_click"}:
            try:
                point = [float(params["x"]), float(params["y"])]
            except (KeyError, TypeError, ValueError):
                point = None
        return dict(self._page.evaluate(
            """(point) => {
              const api = window.__mingle || window.__fixture;
              if (!api?.snapshot) return {};
              const snapshot = api.snapshot();
              const surface = document.querySelector("[data-surface-id]")
                ?.dataset.surfaceId || "";
              let control = null;
              if (point) {
                control = document.elementFromPoint(point[0], point[1])
                  ?.closest("[data-action-id], button") || null;
              }
              const doc = document.documentElement;
              const maxY = Math.max(0, doc.scrollHeight - innerHeight);
              const scrollRegions = Object.fromEntries(
                [...document.querySelectorAll("[data-scroll-region-id]")].map(node => {
                  const max = Math.max(0, node.scrollHeight - node.clientHeight);
                  return [node.dataset.scrollRegionId, {
                    y: Math.round(node.scrollTop), max_y: Math.round(max),
                    top: node.scrollTop <= 4, bottom: node.scrollTop >= max - 4,
                  }];
                })
              );
              return {
                page: snapshot.page || snapshot.pageId || "", surface,
                state: snapshot.state || {},
                action_id: control?.dataset.actionId || "",
                action_label: control?.getAttribute("aria-label")
                  || (control?.innerText || "").trim(),
                control_id: control?.id || "",
                action_disabled: Boolean(control?.disabled),
                route: location.hash || "",
                visits: Array.isArray(snapshot.visits) ? snapshot.visits : [],
                active_entry: snapshot.activeEntry || "",
                history_source: history.state?.from || "",
                back_enabled: document.querySelector("#back")
                  ? !document.querySelector("#back").disabled : null,
                scroll: {
                  y: Math.round(scrollY), max_y: Math.round(maxY),
                  top: scrollY <= 4, bottom: scrollY >= maxY - 4,
                },
                scroll_regions: scrollRegions,
              };
            }""",
            point,
        ) or {})

    def resolve_fixture_grounding(self, element: Any) -> Dict[str, Any]:
        """Resolve one currently visible fixture control without a VLM call.

        This is deliberately unavailable unless the constructor opt-in is set.
        The browser-side resolver reads only repository fixture metadata and
        current visible ``data-action-id`` controls.  It returns diagnostic
        geometry for the click transaction but never mutates the page or writes
        the oracle identity into graph state.
        """
        if not self.fixture_oracle_grounding:
            return {"status": "disabled", "method": "fixture_oracle_grounding"}
        request = {
            "name": str(getattr(element, "name", "") or ""),
            "region": str(getattr(element, "region", "") or ""),
            "element_type": str(getattr(element, "el_type", "") or ""),
            "category": str(getattr(element, "category", "") or ""),
            "back": bool(getattr(element, "back", False)),
            "enabled": getattr(element, "enabled", None),
            "selected": bool(getattr(element, "selected", False)),
        }
        return dict(self._page.evaluate(
            """request => {
              const normalize = value => String(value || "")
                .toLocaleLowerCase().replace(/[^\\p{L}\\p{N}]+/gu, " ")
                .trim().replace(/\\s+/g, " ");
              const tokens = value => new Set(normalize(value).split(" ").filter(Boolean));
              const oracleNode = document.getElementById("fixture-oracle");
              if (!oracleNode) return {
                status: "unavailable", method: "fixture_oracle_grounding",
                reason: "fixture-oracle metadata is absent"
              };
              let oracle;
              try { oracle = JSON.parse(oracleNode.textContent); }
              catch (_error) { return {
                status: "unavailable", method: "fixture_oracle_grounding",
                reason: "fixture-oracle metadata is invalid"
              }; }
              const snapshot = window.__mingle?.snapshot?.() || {};
              const pageId = snapshot.page || document.querySelector("[data-page-id]")?.dataset.pageId || "";
              const pageSpec = (oracle.pages || []).find(row => row.id === pageId) || {};
              const controls = [
                ...(pageSpec.controls || []),
                ...(oracle.surfaces || []).flatMap(surface => surface.controls || []),
              ];
              const controlsById = new Map(controls.map(control => [control.id, control]));
              const rolesByBlock = new Map((pageSpec.blocks || []).map(block => [block.id, block.role]));
              for (const surface of (oracle.surfaces || [])) {
                rolesByBlock.set(surface.id, surface.kind);
              }
              const requestedName = normalize(request.name);
              const requestedTokens = tokens(request.name);
              const requestedType = normalize(request.element_type);
              const compatibleType = (wanted, actual) => {
                if (!wanted || wanted === actual) return true;
                const buttonish = new Set(["button", "icon button", "list item", "menu item", "tab", "link"]);
                return buttonish.has(wanted) && buttonish.has(actual);
              };
              const visible = node => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden"
                  && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0
                  && rect.right > 0 && rect.bottom > 0
                  && rect.left < innerWidth && rect.top < innerHeight;
              };
              const elementType = node => {
                if (node.matches("input,textarea")) return "textbox";
                if (node.classList.contains("switch-button")) return "switch";
                if (node.classList.contains("nav-button")) return "tab";
                if (node.classList.contains("icon-button")) return "icon button";
                if (node.classList.contains("back-button")) return "button";
                if (node.classList.contains("chat-row") || node.classList.contains("contact-row")
                    || node.classList.contains("menu-row")) return "list item";
                return "button";
              };
              const rows = [...document.querySelectorAll("[data-action-id]")]
                .filter(node => {
                  if (!visible(node)) return false;
                  if (controlsById.has(node.dataset.actionId)) return true;
                  return node.getAttribute("aria-current") === "page"
                    || node.getAttribute("aria-pressed") === "true";
                })
                .map(node => {
                  const actionId = node.dataset.actionId;
                  const control = controlsById.get(actionId) || {};
                  const blockId = node.dataset.blockId || "";
                  const aliases = [
                    control.label, control.alternate_label,
                    node.getAttribute("aria-label"), node.getAttribute("placeholder"),
                    node.innerText, actionId.split(".").slice(1).join(" "),
                  ].map(normalize).filter(Boolean);
                  const rect = node.getBoundingClientRect();
                  const actualType = elementType(node);
                  const backLike = actionId.endsWith(".back")
                    || aliases.some(value => /^(back|close|cancel)( |$)/.test(value));
                  let textScore = 0;
                  for (const alias of aliases) {
                    if (requestedName && requestedName === alias) {
                      textScore = Math.max(textScore, 1000);
                      continue;
                    }
                    const aliasTokens = tokens(alias);
                    const common = [...requestedTokens].filter(value => aliasTokens.has(value)).length;
                    if (!common) continue;
                    const requestedContained = [...requestedTokens].every(value => aliasTokens.has(value));
                    const aliasContained = [...aliasTokens].every(value => requestedTokens.has(value));
                    textScore = Math.max(textScore,
                      (requestedContained || aliasContained ? 700 : 300)
                      + common * 20);
                  }
                  const role = rolesByBlock.get(blockId) || "";
                  let score = textScore;
                  if (normalize(request.region) && normalize(request.region) === normalize(role)) score += 120;
                  if (compatibleType(requestedType, actualType)) score += 60;
                  else score -= 80;
                  if (request.back) score += backLike ? 240 : -500;
                  else if (backLike) score -= 120;
                  if (request.enabled === true) score += node.disabled ? -50 : 20;
                  else if (request.enabled === false) score += node.disabled ? 20 : -20;
                  const selected = node.getAttribute("aria-current") === "page"
                    || node.getAttribute("aria-pressed") === "true";
                  if (request.selected === selected) score += 10;
                  return {
                    action_id: actionId, block_id: blockId, role,
                    aliases, element_type: actualType, disabled: Boolean(node.disabled),
                    selected, back_like: backLike, text_score: textScore, score,
                    bbox_xywh: [Math.round(rect.x), Math.round(rect.y),
                                Math.round(rect.width), Math.round(rect.height)],
                    center: [Math.round(rect.x + rect.width / 2),
                             Math.round(rect.y + rect.height / 2)],
                  };
                }).sort((left, right) => right.score - left.score
                  || left.action_id.localeCompare(right.action_id));
              const best = rows[0];
              const runnerUp = rows[1];
              if (!best || best.score < 100
                  || (runnerUp && best.score === runnerUp.score)) {
                return {
                  status: "not_found", method: "fixture_oracle_grounding",
                  page_id: pageId, requested: request,
                  candidates: rows.slice(0, 5),
                  reason: !best ? "no visible fixture controls"
                    : best.score < 100 ? "no structurally credible control"
                    : "ambiguous top-scoring controls",
                };
              }
              return {
                status: "matched", method: "fixture_oracle_grounding",
                page_id: pageId, surface: snapshot.overlay || "none",
                requested: request, ...best,
                score_margin: runnerUp ? best.score - runnerUp.score : best.score,
              };
            }""",
            request,
        ) or {})

    @property
    def vm_platform(self) -> str:
        return self.platform_kind

    @property
    def vm_screen_size(self) -> Tuple[int, int]:
        return self.screen_size

    def reset(self, task_config=None, seed=None, options=None):
        if self.clean_start:
            self._context.clear_cookies()
        self._page.goto(self.start_url, wait_until="domcontentloaded")
        if self.clean_start:
            self._page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            self._page.reload(wait_until="domcontentloaded")
        self._page.wait_for_timeout(100)
        self._step_no = 0
        self.action_history.clear()
        return self._get_obs()

    def relaunch(self, preserve_data: bool = True):
        if not preserve_data:
            self._page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        self._page.goto(self.start_url, wait_until="domcontentloaded")
        self._page.wait_for_timeout(100)
        return self._get_obs()

    def _get_obs(self):
        return {"screenshot": self.controller.get_screenshot(), "terminal": None}

    def step(self, action_json_dict, pause=2):
        self._step_no += 1
        self.is_environment_used = True
        self.action_history.append(action_json_dict)
        self.controller.execute_gui_action(action_json_dict)
        self._page.wait_for_timeout(min(250, max(0, int(float(pause) * 1000))))
        return self._get_obs()

    def close(self):
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
