"""Live adapter that lets M13 reuse the traversal visual runtime.

The collection executor plans; this adapter performs only the already-shared
runtime primitives: live capture, state identification, semantic element
relocation, GUI execution, and settle.  It never reads an accessibility tree and
never trusts coordinates persisted in the graph without rebinding them to the
current screenshot.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional


_INPUT_TYPES = {
    "input", "textbox", "text field", "text_field", "textfield",
    "edittext",
}

_POINTER_ACTIONS = {
    "CLICK", "RIGHT_CLICK", "RIGHT_SINGLE", "DOUBLE_CLICK", "LONG_PRESS",
}
_DIRECT_ACTIONS = {"TYPE", "PRESS", "HOTKEY", "SCROLL", "BACK", "HOME"}
_ACTION_ALIASES = {
    "TAP": "CLICK", "LEFT_CLICK": "CLICK", "RIGHTCLICK": "RIGHT_CLICK",
    "DOUBLECLICK": "DOUBLE_CLICK", "LONGPRESS": "LONG_PRESS",
    "LONG_CLICK": "LONG_PRESS", "DRAG_DROP": "DRAG",
    "DRAG_AND_DROP": "DRAG", "KEY": "PRESS", "KEYBOARD": "PRESS",
    "TYPING": "TYPE", "INPUT_TEXT": "TYPE", "GO_BACK": "BACK",
}
_PARAM_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}")
_PERSISTED_GEOMETRY_KEYS = {
    "x", "y", "x1", "y1", "x2", "y2", "start_x", "start_y",
    "bbox", "region_bbox", "coordinates", "coordinate", "point",
}

_SLIDER_LEVELS = {
    "minimum": 0.0, "min": 0.0, "lowest": 0.0,
    "middle": 0.5, "half": 0.5, "center": 0.5,
    "maximum": 1.0, "max": 1.0, "highest": 1.0,
    "最小": 0.0, "一半": 0.5, "中间": 0.5, "居中": 0.5, "最大": 1.0,
}


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


class EngineVisualAdapter:
    """Adapt one resumed ``VisualTraversalEngine`` to M13's live protocol."""

    def __init__(
        self,
        env: Any,
        engine: Any,
        app_id: str,
        *,
        activate_fn: Optional[Callable[[], Any]] = None,
        pause: float = 0.8,
        state_locator: Any = None,
    ) -> None:
        self.env = env
        self.engine = engine
        self.app_id = str(app_id)
        self.activate_fn = activate_fn
        self.pause = max(0.0, float(pause))
        self.state_locator = state_locator
        self._last_obs: Any = None
        self._last_live_elements: List[Any] = []
        self._result_bindings: Dict[str, Dict[str, Any]] = {}
        self._identity_valid = False
        self._identified_state: Optional[str] = None

    @property
    def current_node_id(self) -> Optional[str]:
        if self._last_obs is None:
            return None
        return self.identify(self._last_obs)

    def activate(self) -> Any:
        self._invalidate_identity()
        if self.activate_fn is not None:
            result = self.activate_fn()
            if isinstance(result, Mapping) and result.get("screenshot") is not None:
                self._last_obs = result
        if self._last_obs is None:
            self._last_obs = self._capture_environment()
        return self._last_obs

    def capture(self) -> Any:
        self._last_obs = self._capture_environment()
        return self._last_obs

    def identify(self, observation: Any) -> Optional[str]:
        if self._identity_valid:
            return self._identified_state
        if self.state_locator is None:
            return self._remember_identity(
                self.engine._router_identify(observation))
        screenshot = observation.get("screenshot") if isinstance(
            observation, Mapping) else None
        if not screenshot:
            return self._remember_identity(None)
        registry = self.engine.registry
        exact = list(registry.exact_frame_state_ids(screenshot))
        if len(exact) == 1:
            return self._remember_identity(str(exact[0]))
        resolution = self.engine.identity_resolver.resolve(screenshot)
        page_ref = ""
        if resolution.known:
            page_state = str(resolution.state_id)
            page_ref = str(
                registry.page_id_of(page_state)
                or self.engine._state_data.get(page_state, {}).get("page_id")
                or ""
            )
        else:
            judge = getattr(self.engine, "page_judge", None)
            shortlisted = tuple(getattr(
                judge, "last_candidate_page_ids", ()) or ())
            if (getattr(judge, "last_selection_status", "") == "selected"
                    and len(shortlisted) == 1):
                page_ref = str(shortlisted[0])
        if not page_ref:
            return self._remember_identity(None)
        return self._remember_identity(
            self.state_locator.locate(
                screenshot,
                self._known_state_candidates(page_ref),
                page_ref=page_ref,
            )
        )

    def _remember_identity(self, state_id: Any) -> Optional[str]:
        self._identified_state = (
            str(state_id) if state_id is not None and str(state_id) else None)
        self._identity_valid = True
        return self._identified_state

    def _invalidate_identity(self) -> None:
        self._identity_valid = False
        self._identified_state = None

    def _known_state_candidates(self, page_ref: str) -> List[Dict[str, Any]]:
        candidates = []
        registry = self.engine.registry
        for state_ref, state in self.engine._state_data.items():
            if str(state.get("page_id") or "") != page_ref:
                continue
            regions: Dict[str, List[str]] = {}
            for element in state.get("elements") or []:
                if getattr(element, "interactive", None) is False:
                    continue
                name = str(getattr(element, "name", "") or "").strip()
                if not name:
                    continue
                region = str(
                    getattr(element, "region", "")
                    or getattr(element, "region_id", "")
                    or "page"
                ).strip()
                regions.setdefault(region, [])
                if name not in regions[region]:
                    regions[region].append(name)
            screenshot = None
            path = registry.known_path(str(state_ref))
            if path:
                try:
                    with open(path, "rb") as stream:
                        screenshot = stream.read()
                except OSError:
                    screenshot = None
            facts = state.get("observed_facts") or {}
            summary = ", ".join(
                f"{key}={value}" for key, value in facts.items()) \
                if isinstance(facts, Mapping) else ""
            candidates.append({
                "state_ref": str(state_ref),
                "page_ref": page_ref,
                "state_name": str(state.get("variant_id") or state_ref),
                "state_summary": summary,
                "regions": [
                    {"name": name, "operations": operations}
                    for name, operations in regions.items()
                ],
                "screenshot": screenshot,
            })
        return candidates

    def ground(self, action_spec: Mapping[str, Any], observation: Any) -> Any:
        """Rebind a graph edge or capability ref to this live frame."""
        kind = str(action_spec.get("kind") or "")
        if kind == "graph_edge":
            return self._ground_graph_edge(action_spec, observation)
        if kind == "capability":
            return self._ground_capability(action_spec, observation)
        # PrerequisiteRuntime actions intentionally have no graph/capability
        # kind. They must still cross the same screenshot-only grounding gate.
        return self._ground_prerequisite_action(action_spec, observation)

    def ground_workflow_click(
        self,
        target: str,
        decision: Mapping[str, Any],
        observation: Any,
    ) -> Optional[Dict[str, Any]]:
        """Convert one reviewed current-frame normalized point to a click."""
        click = decision.get("next_click")
        if not isinstance(click, Mapping) \
                or _norm(click.get("target")) != _norm(target):
            return None
        bbox = click.get("bbox_1000")
        point = click.get("click_point_1000")
        try:
            bbox = [int(value) for value in bbox]
            point = [int(value) for value in point]
        except (TypeError, ValueError):
            return None
        if (len(bbox) != 4 or len(point) != 2
                or not (0 <= bbox[0] < bbox[2] <= 1000)
                or not (0 <= bbox[1] < bbox[3] <= 1000)
                or not (bbox[0] <= point[0] <= bbox[2])
                or not (bbox[1] <= point[1] <= bbox[3])):
            return None
        screenshot = observation.get("screenshot") if isinstance(
            observation, Mapping) else None
        if not screenshot:
            return None
        try:
            import io
            from PIL import Image
            width, height = Image.open(io.BytesIO(screenshot)).size
        except Exception:
            return None
        x = round(point[0] * width / 1000)
        y = round(point[1] * height / 1000)
        window = getattr(
            getattr(self.engine, "perception", None),
            "window_px_override", None)
        if isinstance(window, (list, tuple)) and len(window) == 4:
            wx, wy, ww, wh = [int(value) for value in window]
            if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
                return None
        return {
            "actions": [{
                "action_type": "CLICK",
                "parameters": {"x": x, "y": y, "button": "left"},
            }],
            "gui_action_count": 1,
            "element_name": str(target),
            "grounding_source": "workflow_agent_current_frame",
            "workflow_bbox_1000": bbox,
            "workflow_click_point_1000": point,
        }

    def grounded_elements(self, observation: Any) -> List[Dict[str, Any]]:
        """Return freshly perceived controls for prerequisite VLM grounding."""
        screenshot = observation.get("screenshot") if isinstance(
            observation, Mapping) else None
        if screenshot is None:
            self._last_live_elements = []
            return []
        try:
            elements = list(self.engine.perception.detect_and_name(screenshot) or [])
        except Exception:
            self._last_live_elements = []
            return []
        self._last_live_elements = elements
        result: List[Dict[str, Any]] = []
        for element in elements:
            if hasattr(element, "to_dict") and callable(element.to_dict):
                value = element.to_dict()
            else:
                value = {
                    "id": getattr(element, "id", ""),
                    "name": getattr(element, "name", ""),
                    "type": getattr(element, "el_type", ""),
                    "interactive": getattr(element, "interactive", None),
                }
            # Geometry is useful to the visual agent for disambiguation but is
            # never accepted back as an execution target without re-grounding.
            result.append(dict(value))
        return result

    def execute(self, grounded_action: Mapping[str, Any]) -> Any:
        dynamic_recipe = grounded_action.get("dynamic_recipe")
        if isinstance(dynamic_recipe, list):
            if not isinstance(grounded_action, MutableMapping):
                raise ValueError("dynamic recipe grounding must be mutable for action accounting")
            return self._execute_dynamic_recipe(grounded_action, dynamic_recipe)
        actions = grounded_action.get("actions")
        if not isinstance(actions, list):
            action = grounded_action.get("action")
            actions = [action] if isinstance(action, Mapping) else []
        if not actions:
            raise ValueError("grounded action contains no GUI actions")
        if isinstance(grounded_action, MutableMapping):
            grounded_action["_executed_gui_actions"] = 0
            grounded_action["primitive_actions"] = []
        result = None
        for action in actions:
            if not isinstance(action, Mapping):
                raise ValueError("grounded GUI action must be an object")
            primitive = dict(action)
            self._invalidate_identity()
            result = self.env.step(primitive, pause=self.pause)
            if isinstance(grounded_action, MutableMapping):
                grounded_action["primitive_actions"].append(primitive)
                grounded_action["_executed_gui_actions"] += 1
        if isinstance(result, Mapping):
            self._last_obs = result
        return result

    def _execute_dynamic_recipe(
        self,
        grounding: MutableMapping[str, Any],
        recipe: List[Any],
    ) -> Any:
        """Execute a semantic recipe as a fail-closed sequence of live rebinds."""
        actual_actions: List[Dict[str, Any]] = []
        step_groundings: List[Dict[str, Any]] = []
        grounding["actions"] = actual_actions
        grounding["primitive_actions"] = actual_actions
        grounding["recipe_groundings"] = step_groundings
        grounding["gui_action_count"] = 0
        grounding["_executed_gui_actions"] = 0
        result: Any = self._last_obs

        for index, raw_step in enumerate(recipe):
            if not isinstance(raw_step, Mapping):
                grounding["failed_recipe_index"] = index
                raise ValueError(f"execution_recipe[{index}] is not an object")
            try:
                # A capture is mandatory even for keyboard-only primitives. Any
                # pointer geometry is then derived from this frame alone.
                before = self.capture()
                source_node = self.identify(before)
                semantic_step = self._apply_result_binding(
                    raw_step, self._result_bindings)
                step_grounded = self._ground_recipe_step(
                    semantic_step, before)
                if step_grounded is None:
                    raise RuntimeError("semantic recipe step could not be grounded")
                actions = step_grounded.get("actions")
                if not isinstance(actions, list) or not actions:
                    raise RuntimeError("semantic recipe step produced no GUI primitive")
                record = {
                    "recipe_step_index": index,
                    "source_node_id": source_node,
                    "semantic_step": copy.deepcopy(dict(semantic_step)),
                    "grounding_source": step_grounded.get("grounding_source", ""),
                    "actions": [],
                }
                step_groundings.append(record)
                for action in actions:
                    if not isinstance(action, Mapping):
                        raise RuntimeError("grounded recipe primitive is not an object")
                    primitive = copy.deepcopy(dict(action))
                    self._invalidate_identity()
                    result = self.env.step(primitive, pause=self.pause)
                    actual_actions.append(primitive)
                    record["actions"].append(primitive)
                    grounding["gui_action_count"] = len(actual_actions)
                    grounding["_executed_gui_actions"] = len(actual_actions)
                    if isinstance(result, Mapping):
                        self._last_obs = result
                result = self.settle(result)
                settled_node = self.identify(result)
                record["settled_node_id"] = settled_node
                binding_name = self._binding_name(raw_step.get("bind_result"))
                if binding_name:
                    binding = self._introduced_region_binding(
                        source_node, settled_node)
                    if binding is None:
                        raise RuntimeError(
                            f"result binding {binding_name!r} is unresolved")
                    self._result_bindings[binding_name] = binding
                    record["result_binding"] = copy.deepcopy(binding)
            except Exception as exc:
                grounding["failed_recipe_index"] = index
                grounding["failure_reason"] = str(exc)
                # Do not execute any later recipe step. The caller can record
                # the completed primitive count from this same grounding dict.
                raise RuntimeError(
                    f"execution_recipe step {index} failed: {exc}"
                ) from exc
        return result

    def _ground_recipe_step(
        self, step: Mapping[str, Any], observation: Any
    ) -> Optional[Dict[str, Any]]:
        # This path deliberately shares the prerequisite primitive grounder: it
        # accepts semantic selectors, ignores persisted geometry, and validates
        # every direct keyboard/scroll contract before env.step.
        return self._ground_prerequisite_action(step, observation)

    @staticmethod
    def _binding_name(raw: Any) -> str:
        if isinstance(raw, Mapping):
            return str(raw.get("name") or "").strip()
        return str(raw or "").strip()

    @staticmethod
    def _apply_result_binding(
        step: Mapping[str, Any], bindings: Mapping[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        resolved = copy.deepcopy(dict(step))
        selector = resolved.get("selector")
        if not isinstance(selector, Mapping):
            return resolved
        selector = dict(selector)
        name = str(selector.pop("region_ref", "") or "").strip()
        if not name:
            resolved["selector"] = selector
            return resolved
        binding = bindings.get(name)
        if not isinstance(binding, Mapping):
            raise RuntimeError(f"unknown result binding {name!r}")
        region_ids = [
            str(value) for value in binding.get("region_ids") or [] if value]
        if not region_ids:
            raise RuntimeError(f"result binding {name!r} has no Region")
        selector["region_ids"] = region_ids
        resolved["selector"] = selector
        return resolved

    def _introduced_region_binding(
        self, source_node: Any, target_node: Any,
    ) -> Optional[Dict[str, Any]]:
        data = getattr(self.engine, "_state_data", {}).get(
            str(target_node or "")) or {}
        transition = data.get("region_transition")
        if not isinstance(transition, Mapping):
            return None
        if str(transition.get("source_state_id") or "") != str(
                source_node or ""):
            return None
        result = transition.get("result_binding")
        if not isinstance(result, Mapping) or str(
                result.get("status") or "") not in {"bound", "candidate_set"}:
            return None
        region_ids = [
            str(value) for value in result.get("region_ids") or [] if value]
        if not region_ids:
            return None
        return {
            "kind": "introduced_region",
            "source_node_id": str(source_node or ""),
            "target_node_id": str(target_node or ""),
            "attempt_id": str(result.get("attempt_id") or ""),
            "region_ids": region_ids,
        }

    def settle(self, execution_result: Any = None) -> Any:
        observation = execution_result if isinstance(execution_result, Mapping) \
            else self._last_obs
        if observation is None:
            observation = self._capture_environment()
        settled = self.engine._settle(observation)
        self._last_obs = settled
        return settled

    # -- grounding -----------------------------------------------------

    def _ground_graph_edge(self, spec: Mapping[str, Any], obs: Any) -> Any:
        edge = spec.get("edge") or {}
        if not isinstance(edge, Mapping):
            return None
        saved_action = edge.get("action")
        # A discovery prerequisite edge is a weighted record of a runtime-owned
        # setup recipe, not a coordinate-replay shortcut.  Returning None makes
        # M13 resolve the declared prerequisite and replan from the resulting
        # live surface; otherwise env.step would receive an unsupported SEQUENCE
        # or replay a setup that may create duplicate resources.
        if str(edge.get("transition_kind") or "") == "prerequisite_setup" \
                or (isinstance(saved_action, Mapping)
                    and str(saved_action.get("action_type") or "").upper()
                    == "SEQUENCE"):
            return None
        if isinstance(saved_action, Mapping) \
                and str(saved_action.get("action_type") or "").upper() != "CLICK":
            return {
                "actions": [copy.deepcopy(dict(saved_action))],
                "gui_action_count": int(edge.get("action_steps", 1) or 1),
                "grounding_source": "live_non_click_reuse",
            }
        source = str(spec.get("source_node") or edge.get("source") or "")
        target = self._stored_element(
            source,
            element_ids=[edge.get("element_id")],
            labels=[edge.get("element_label"), edge.get("semantic_description")],
            region=str(edge.get("region") or ""),
        )
        action = self._click_for(target, obs)
        if action is None:
            return None
        return {
            "actions": [action],
            "gui_action_count": 1,
            "element_id": str(getattr(target, "id", "")),
            "element_name": str(getattr(target, "name", "") or ""),
            "grounding_source": "graph_element_live_relocation",
        }

    def _ground_capability(self, spec: Mapping[str, Any], obs: Any) -> Any:
        ref = spec.get("capability_ref") or {}
        if not isinstance(ref, Mapping):
            return None
        node_id = str(ref.get("node_id") or self.identify(obs) or "")
        value = str(ref.get("value") or "")
        spec_params = spec.get("params") or {}
        ref_params = ref.get("params") or {}
        params: Dict[str, Any] = {}
        if isinstance(spec_params, Mapping):
            params.update(spec_params)
        # The serialized ref is authoritative: catalog composition binds the
        # recipe and its parameters together, and M13 preserves that object.
        if isinstance(ref_params, Mapping):
            params.update(ref_params)
        slot = str(ref.get("slot") or "")
        if not value and slot and slot in params:
            value = str(params[slot])
        if slot and value and value != "<runtime>" and slot not in params:
            params[slot] = value

        recipe = _execution_recipe_from_mapping(ref)
        if recipe:
            bound_recipe = _bind_execution_recipe(recipe, params)
            return {
                "dynamic_recipe": bound_recipe,
                "actions": [],
                "primitive_actions": [],
                "recipe_groundings": [],
                "gui_action_count": 0,
                "_executed_gui_actions": 0,
                "capability_id": str(ref.get("capability_id") or ""),
                "grounding_source": "capability_dynamic_visual_recipe",
            }

        element_ids: List[Any] = []
        element_map = ref.get("element_map") or {}
        if isinstance(element_map, Mapping) and value:
            for key, values in element_map.items():
                if _norm(key) == _norm(value):
                    if isinstance(values, (list, tuple)):
                        element_ids.extend(values)
                    else:
                        element_ids.append(values)
                    break
        if not element_ids:
            raw_ids = ref.get("elements") or []
            element_ids.extend(raw_ids if isinstance(raw_ids, list) else [raw_ids])
        target = self._stored_element(
            node_id,
            element_ids=element_ids,
            labels=[ref.get("name")],
            region=str(ref.get("region") or ""),
        )
        click = self._click_for(target, obs)
        if click is None:
            return None

        param_type = " ".join(str(ref.get("param_type") or "").lower().split())
        element_type = " ".join(
            str(getattr(target, "el_type", "") or "").lower().split())
        actions: List[Dict[str, Any]] = [click]
        text_value = value
        if not text_value and params:
            text_value = str(next(iter(params.values())))
        if text_value and (param_type in {"string", "text"}
                           or element_type in _INPUT_TYPES):
            actions.append({
                "action_type": "TYPE",
                "parameters": {"text": text_value},
            })
        return {
            "actions": actions,
            "gui_action_count": len(actions),
            "element_id": str(getattr(target, "id", "")),
            "element_name": str(getattr(target, "name", "") or ""),
            "grounding_source": "capability_element_live_relocation",
        }

    def _ground_text_input_action(
        self, primitive: Mapping[str, Any], obs: Any
    ) -> Any:
        """Refocus one selector-bound input before typing on a fresh frame."""
        parameters = primitive.get("parameters")
        parameters = (
            dict(parameters) if isinstance(parameters, Mapping) else {})
        text = parameters.get(
            "text", primitive.get("text", primitive.get("value")))
        if text is None:
            return None
        current_node = self.identify(obs)
        if not current_node:
            return None
        self.grounded_elements(obs)
        target = self._live_or_stored_element(
            current_node,
            element_ids=[primitive.get("element_id")],
            labels=[
                primitive.get("element_label"),
                primitive.get("name"),
                primitive.get("label"),
            ],
            region=str(primitive.get("region") or ""),
            region_ids=primitive.get("region_ids") or [],
            element_type=str(primitive.get("element_type") or "input"),
        )
        input_types = {_norm(value) for value in _INPUT_TYPES}
        if target is None or _norm(
                getattr(target, "el_type", "")) not in input_types:
            return None
        focus = self._click_for(target, obs)
        if focus is None:
            return None
        return {
            "actions": [
                focus,
                {
                    "action_type": "TYPE",
                    "parameters": {"text": str(text)},
                },
            ],
            "gui_action_count": 2,
            "element_id": str(getattr(target, "uid", "") or getattr(
                target, "id", "")),
            "element_name": str(getattr(target, "name", "") or ""),
            "grounding_source": "type_input_live_relocation",
        }

    def _ground_prerequisite_action(
        self, spec: Mapping[str, Any], obs: Any
    ) -> Any:
        """Ground one setup/cleanup primitive from semantic selectors only."""
        nested = spec.get("action")
        if isinstance(nested, Mapping):
            primitive = dict(nested)
            # Labels belong to the surrounding recipe item in many generated
            # setup recipes; carry only semantic selectors into the primitive.
            for key in (
                "element_id", "element_label", "name", "region",
                "element_type", "selector",
            ):
                if key not in primitive and key in spec:
                    primitive[key] = spec.get(key)
        else:
            primitive = dict(spec)

        selector = primitive.get("selector")
        if isinstance(selector, str):
            selector = {"element_label": selector}
        if isinstance(selector, Mapping):
            # Only semantic selector keys are carried into grounding. Persisted
            # x/y or bbox values (including those in a legacy alias) are never
            # copied into an environment action.
            for source_key, target_key in (
                ("element_id", "element_id"),
                ("element_label", "element_label"),
                ("label", "element_label"),
                ("name", "name"),
                ("text", "label"),
                ("region", "region"),
                ("region_ids", "region_ids"),
                ("element_type", "element_type"),
                ("type", "element_type"),
                ("role", "element_type"),
            ):
                if target_key not in primitive and source_key in selector:
                    primitive[target_key] = selector.get(source_key)

        raw_type = primitive.get("action_type")
        if not raw_type:
            raw_type = nested if isinstance(nested, str) else primitive.get("verb")
        action_type = str(raw_type or "").strip().upper().replace(" ", "_")
        action_type = _ACTION_ALIASES.get(action_type, action_type)
        if action_type == "SET_SLIDER":
            current_node = self.identify(obs)
            if not current_node:
                return None
            self.grounded_elements(obs)
            selector_value = primitive.get("selector")
            if isinstance(selector_value, str):
                selector_value = {"element_label": selector_value}
            if not isinstance(selector_value, Mapping):
                return None
            target = self._live_or_stored_element(
                current_node,
                element_ids=[selector_value.get("element_id")],
                labels=[selector_value.get("element_label"),
                        selector_value.get("label"),
                        selector_value.get("name")],
                region=str(selector_value.get("region") or ""),
                region_ids=selector_value.get("region_ids") or [],
                element_type=str(selector_value.get("element_type")
                                 or selector_value.get("type") or "slider"),
            )
            if target is None or _norm(getattr(target, "el_type", "")) not in {
                "slider", "range", "rangeslider",
            }:
                return None
            params = primitive.get("parameters") or {}
            raw_level = params.get("level") if isinstance(params, Mapping) else None
            level = _SLIDER_LEVELS.get(str(raw_level or "").strip().casefold())
            bbox = list(getattr(target, "bbox_xywh", []) or [])
            if level is None or len(bbox) != 4:
                return None
            x, y, width, height = (int(value) for value in bbox)
            if max(width, height) < 40:
                return None
            fraction = 0.03 + level * 0.94
            if width >= height:
                point = (round(x + width * fraction), round(y + height / 2))
            else:
                point = (round(x + width / 2),
                         round(y + height * (1.0 - fraction)))
            return {
                "actions": [{"action_type": "CLICK", "parameters": {
                    "x": point[0], "y": point[1],
                }}],
                "gui_action_count": 1,
                "element_id": str(getattr(target, "id", "")),
                "element_name": str(getattr(target, "name", "") or ""),
                "slider_level": str(raw_level),
                "slider_fraction": level,
                "grounding_source": "semantic_slider_live_track",
            }
        if action_type == "DRAG":
            current_node = self.identify(obs)
            if not current_node:
                return None
            self.grounded_elements(obs)

            def target_from(selector_value: Any) -> Any:
                if isinstance(selector_value, str):
                    selector_value = {"element_label": selector_value}
                if not isinstance(selector_value, Mapping):
                    return None
                return self._live_or_stored_element(
                    current_node,
                    element_ids=[selector_value.get("element_id")],
                    labels=[
                        selector_value.get("element_label"),
                        selector_value.get("label"),
                        selector_value.get("name"),
                        selector_value.get("text"),
                    ],
                    region=str(selector_value.get("region") or ""),
                    region_ids=selector_value.get("region_ids") or [],
                    element_type=str(
                        selector_value.get("element_type")
                        or selector_value.get("type") or ""),
                )

            source_target = target_from(
                primitive.get("source_selector") or primitive.get("selector"))
            destination_target = target_from(primitive.get("target_selector"))
            if source_target is None or destination_target is None:
                return None
            start = self.engine._live_center_for(source_target, obs)
            end = self.engine._live_center_for(destination_target, obs)
            if start is None or end is None:
                return None
            for target, center in (
                (source_target, start), (destination_target, end)
            ):
                region_bbox = list(getattr(target, "region_bbox", []) or [])
                if len(region_bbox) == 4:
                    x0, y0, x1, y1 = region_bbox
                    if not (x0 <= center[0] <= x1 and y0 <= center[1] <= y1):
                        return None
            return {
                "actions": [{
                    "action_type": "DRAG",
                    "parameters": {
                        "x1": int(start[0]), "y1": int(start[1]),
                        "x2": int(end[0]), "y2": int(end[1]),
                    },
                }],
                "gui_action_count": 1,
                "source_element_name": str(
                    getattr(source_target, "name", "") or ""),
                "target_element_name": str(
                    getattr(destination_target, "name", "") or ""),
                "grounding_source": "semantic_drag_live_relocation",
            }
        if action_type == "TYPE" and isinstance(selector, Mapping) and selector:
            return self._ground_text_input_action(primitive, obs)

        if action_type in _POINTER_ACTIONS:
            current_node = self.identify(obs)
            if not current_node:
                return None
            # Every pointer primitive may follow a prior setup action that
            # changed the surface. Refresh here; never reuse a prior recipe
            # step's element geometry.
            self.grounded_elements(obs)
            element_id = primitive.get("element_id")
            labels = [
                primitive.get("element_label"),
                primitive.get("name"),
                primitive.get("label"),
            ]
            target = self._live_or_stored_element(
                current_node,
                element_ids=[element_id],
                labels=labels,
                region=str(primitive.get("region") or ""),
                region_ids=primitive.get("region_ids") or [],
                element_type=str(primitive.get("element_type") or ""),
            )
            action = self._pointer_for(target, obs, action_type)
            if action is None:
                return None
            return {
                "actions": [action],
                "gui_action_count": 1,
                "element_id": str(getattr(target, "id", "")),
                "element_name": str(getattr(target, "name", "") or ""),
                "grounding_source": "prerequisite_live_element_relocation",
            }

        if action_type not in _DIRECT_ACTIONS:
            return None
        parameters = primitive.get("parameters")
        parameters = dict(parameters) if isinstance(parameters, Mapping) else {}
        if action_type == "TYPE":
            text = parameters.get("text", primitive.get("text", primitive.get("value")))
            if text is None:
                return None
            parameters = {"text": str(text)}
        elif action_type == "PRESS":
            key = parameters.get("key", primitive.get("key"))
            if not isinstance(key, str) or not key.strip():
                return None
            parameters = {"key": key.strip()}
        elif action_type == "HOTKEY":
            keys = parameters.get("keys", primitive.get("keys"))
            if isinstance(keys, str):
                keys = [value.strip() for value in keys.split("+") if value.strip()]
            if not isinstance(keys, list) or not keys or not all(
                    isinstance(key, str) and key.strip() for key in keys):
                return None
            parameters = {"keys": [key.strip() for key in keys]}
        elif action_type == "SCROLL":
            for key in ("direction", "amount", "dx", "dy", "frac", "slow"):
                if key not in parameters and key in primitive:
                    parameters[key] = primitive.get(key)
            if not ({"direction", "dy", "dx"} & set(parameters)):
                return None
            # Coordinates supplied by a recipe are stale and unnecessary for a
            # keyboard/wheel scroll. Keep only movement semantics.
            parameters.pop("x", None)
            parameters.pop("y", None)
            if not bool(getattr(self.engine, "_is_touch", False)) \
                    and "direction" in parameters:
                direction = str(parameters.pop("direction") or "").lower()
                try:
                    amount = max(1, int(parameters.pop("amount", 1) or 1))
                except (TypeError, ValueError):
                    return None
                if direction not in {"up", "down"}:
                    return None
                parameters["dy"] = amount if direction == "up" else -amount
        elif action_type == "BACK":
            if bool(getattr(self.engine, "_is_touch", False)):
                parameters = {}
            else:
                action_type = "HOTKEY"
                parameters = {"keys": ["alt", "left"]}
        elif action_type == "HOME":
            if not bool(getattr(self.engine, "_is_touch", False)):
                return None
            parameters = {}
        return {
            "actions": [{"action_type": action_type, "parameters": parameters}],
            "gui_action_count": 1,
            "grounding_source": "prerequisite_explicit_non_pointer",
        }

    def _live_or_stored_element(
        self,
        node_id: str,
        *,
        element_ids: Iterable[Any],
        labels: Iterable[Any],
        region: str = "",
        region_ids: Iterable[Any] = (),
        element_type: str = "",
    ) -> Any:
        wanted_ids = {str(value) for value in element_ids if value not in (None, "")}
        wanted_labels = [_norm(value) for value in labels if _norm(value)]
        wanted_region_ids = {
            str(value) for value in region_ids if value not in (None, "")}
        scoped_matches = []
        for element in self._last_live_elements:
            if not _element_matches_scope(
                    element, region, element_type, wanted_region_ids):
                continue
            if wanted_ids and (
                str(getattr(element, "id", "")) in wanted_ids
                or str(getattr(element, "uid", "")) in wanted_ids
            ):
                return element
            name = _norm(getattr(element, "name", ""))
            if any(name == label or name in label or label in name
                   for label in wanted_labels):
                scoped_matches.append(element)
        if scoped_matches:
            return scoped_matches[0] if (
                len(scoped_matches) == 1 or not wanted_region_ids) else None
        return self._stored_element(
            node_id,
            element_ids=element_ids,
            labels=labels,
            region=region,
            region_ids=wanted_region_ids,
            element_type=element_type,
        )

    def _stored_element(
        self,
        node_id: str,
        *,
        element_ids: Iterable[Any],
        labels: Iterable[Any],
        region: str = "",
        region_ids: Iterable[Any] = (),
        element_type: str = "",
    ) -> Any:
        data = getattr(self.engine, "_state_data", {}).get(node_id) or {}
        elements = list(data.get("elements") or [])
        wanted_ids = {str(value) for value in element_ids if value not in (None, "")}
        wanted_region_ids = {
            str(value) for value in region_ids if value not in (None, "")}
        if wanted_ids:
            for element in elements:
                if (str(getattr(element, "id", "")) in wanted_ids
                        or str(getattr(element, "uid", "")) in wanted_ids) \
                        and _element_matches_scope(
                            element, region, element_type, wanted_region_ids):
                    return element
        wanted_labels = [_norm(value) for value in labels if _norm(value)]
        region = str(region or "")
        for wanted in wanted_labels:
            exact = [
                element for element in elements
                if _norm(getattr(element, "name", "")) == wanted
                and _element_matches_scope(
                    element, region, element_type, wanted_region_ids)
            ]
            if exact:
                return exact[0] if (
                    len(exact) == 1 or not wanted_region_ids) else None
            fuzzy = [
                element for element in elements
                if (_norm(getattr(element, "name", "")) in wanted
                    or wanted in _norm(getattr(element, "name", "")))
                and _element_matches_scope(
                    element, region, element_type, wanted_region_ids)
            ]
            if fuzzy:
                return fuzzy[0] if (
                    len(fuzzy) == 1 or not wanted_region_ids) else None
        return None

    def _click_for(self, target: Any, obs: Any) -> Optional[Dict[str, Any]]:
        return self._pointer_for(target, obs, "CLICK")

    def _pointer_for(
        self, target: Any, obs: Any, action_type: str
    ) -> Optional[Dict[str, Any]]:
        if target is None:
            return None
        perception = getattr(self.engine, "perception", None)
        previous_semantic = bool(getattr(
            perception, "use_semantic_inventory", False))
        semantic_only = str(getattr(
            target, "geometry_status", "") or "") == "semantic_only"
        if semantic_only and perception is not None:
            perception.use_semantic_inventory = True
        try:
            center = self.engine._live_center_for(target, obs)
        finally:
            if semantic_only and perception is not None:
                perception.use_semantic_inventory = previous_semantic
        if center is None:
            return None
        region_bbox = list(getattr(target, "region_bbox", []) or [])
        if len(region_bbox) == 4:
            x0, y0, x1, y1 = region_bbox
            if not (x0 <= center[0] <= x1 and y0 <= center[1] <= y1):
                return None
        return {
            "action_type": action_type,
            "parameters": {
                "x": int(center[0]), "y": int(center[1]),
                "button": "right" if action_type in {
                    "RIGHT_CLICK", "RIGHT_SINGLE"
                } else "left",
            },
        }

    def _capture_environment(self) -> Any:
        for name in ("_get_obs", "get_obs", "capture"):
            method = getattr(self.env, name, None)
            if callable(method):
                observation = method()
                if observation is not None:
                    return observation
        raise RuntimeError("environment exposes no screenshot observation method")


def _execution_recipe_from_mapping(raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
    recipe: Any = raw.get("execution_recipe")
    if recipe is None:
        recipe = raw.get("action_recipe")
    if recipe is None:
        recipe = raw.get("actions")
    if isinstance(recipe, Mapping):
        recipe = [recipe]
    if not isinstance(recipe, list):
        return []
    return [copy.deepcopy(dict(step)) for step in recipe if isinstance(step, Mapping)]


def _bind_execution_recipe(
    recipe: List[Dict[str, Any]], params: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Bind ``{{slot}}`` values without evaluating expressions or paths."""
    bound: List[Dict[str, Any]] = []
    for index, step in enumerate(recipe):
        value = _bind_recipe_value(step, params)
        value = _without_persisted_geometry(value)
        if not isinstance(value, dict):
            raise ValueError(f"execution_recipe[{index}] did not bind to an object")
        bound.append(value)
    if not bound:
        raise ValueError("execution_recipe is empty")
    return bound


def _bind_recipe_value(value: Any, params: Mapping[str, Any]) -> Any:
    if isinstance(value, Mapping):
        # Keys are schema, never templates. This prevents a parameter from
        # injecting a new action field such as action_type or coordinates.
        return {key: _bind_recipe_value(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [_bind_recipe_value(item, params) for item in value]
    if not isinstance(value, str):
        return copy.deepcopy(value)

    exact = _PARAM_PLACEHOLDER.fullmatch(value)
    if exact:
        replacement = _recipe_param(exact.group(1), params)
        return copy.deepcopy(replacement)

    def replace(match: re.Match[str]) -> str:
        replacement = _recipe_param(match.group(1), params)
        return str(replacement)

    result = _PARAM_PLACEHOLDER.sub(replace, value)
    if "{{" in result or "}}" in result:
        raise ValueError(f"unresolved or malformed recipe placeholder: {value!r}")
    return result


def _recipe_param(name: str, params: Mapping[str, Any]) -> Any:
    if name not in params:
        raise ValueError(f"execution_recipe requires missing parameter {name!r}")
    value = params[name]
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        raise ValueError(f"execution_recipe parameter {name!r} must be a scalar")
    if isinstance(value, str) and value.strip() == "<runtime>":
        raise ValueError(f"execution_recipe parameter {name!r} is unresolved")
    return value


def _without_persisted_geometry(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_persisted_geometry(item)
            for key, item in value.items()
            if str(key).casefold() not in _PERSISTED_GEOMETRY_KEYS
        }
    if isinstance(value, list):
        return [_without_persisted_geometry(item) for item in value]
    return value


def _element_matches_scope(
    element: Any, region: str, element_type: str,
    region_ids: Iterable[Any] = (),
) -> bool:
    wanted_region_ids = {
        str(value) for value in region_ids if value not in (None, "")}
    if wanted_region_ids and str(
            getattr(element, "region_id", "") or "") not in wanted_region_ids:
        return False
    wanted_region = _norm(region)
    if (wanted_region and wanted_region != "fullscreen"
            and wanted_region not in {
                _norm(getattr(element, "region", "")),
                _norm(getattr(element, "region_id", "")),
            }):
        return False
    if not element_type:
        return True
    actual = _norm(getattr(element, "el_type", ""))
    wanted = _norm(element_type)
    input_aliases = {_norm(value) for value in _INPUT_TYPES}
    if wanted in input_aliases and actual in input_aliases:
        return True
    return actual == wanted or (actual and wanted and (
        actual in wanted or wanted in actual
    ))


__all__ = ["EngineVisualAdapter"]
