"""Offline regression for execution-state plus Page/Variant identity."""
from __future__ import annotations

import io
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.visual_traversal.visual_state import (
    VisualStateRegistry,
    compute_page_id,
    compute_variant_id,
    observed_variant_facts,
    signature_names,
    variant_signature,
)


def _png(colour: tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (320, 240), colour).save(stream, format="PNG")
    return stream.getvalue()


@dataclass
class E:
    name: str
    category: str = "navigation"
    selected: bool = False
    region: str = ""
    group: str = ""
    stateful: bool = False
    state_key: str = ""
    state_value: str = ""
    enabled: bool | None = True
    requires_permission: bool = False
    blocked_reason: str = ""
    effect_scope: str = ""


def _register(registry, root: Path, name: str, shot: bytes, elements,
              region_set, page_name: str):
    path = root / f"{name}.png"
    path.write_bytes(shot)
    names = signature_names(elements)
    sid, is_new = registry.register(
        shot, str(path), button_names=names, region_set=region_set,
        page_name=page_name, judge=lambda *_: False,
    )
    if is_new:
        registry.set_buttons(sid, elements)
    return sid, is_new


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        registry = VisualStateRegistry()
        layout = {"nav_sidebar:r1", "content:r2"}

        off, off_new = _register(
            registry, root, "off", _png((40, 40, 40)),
            [E("Bluetooth", selected=True), E("Turn on Bluetooth", "shallow")],
            layout, "Bluetooth")
        on, on_new = _register(
            registry, root, "on", _png((80, 80, 80)),
            [E("Bluetooth", selected=True), E("Turn off Bluetooth", "shallow"),
             E("Pair New Device", "shallow"), E("Connected Devices", "shallow")],
            layout, "Bluetooth")
        assert off_new and on_new and off != on, (
            "Bluetooth off/on expose different function sets and must split")
        assert registry.page_id_of(off) == registry.page_id_of(on)
        assert registry.variant_id_of(off) != registry.variant_id_of(on)
        assert len(registry.variants_for_page(registry.page_id_of(off))) == 2
        stable_page = registry.page_id_of(off)
        registry.record_page_variant(off, "", elements=["Turn on Bluetooth"])
        assert registry.page_id_of(off) == stable_page, (
            "a missing revisit label must not erase an established page mapping")

        on_again, is_new = _register(
            registry, root, "on_again", _png((82, 82, 82)),
            [E("Bluetooth", selected=True), E("Turn off Bluetooth", "shallow"),
             E("Pair New Device", "shallow"), E("Connected Devices", "shallow")],
            layout, "Bluetooth")
        assert not is_new and on_again == on

        app_layout = {"nav_sidebar:r1", "content:r-apps"}
        acc, _ = _register(
            registry, root, "acc", _png((120, 80, 80)),
            [E("Applications", selected=True),
             E("Accerciser", selected=True, group="application-list"),
             E("Notifications", "shallow")], app_layout, "Applications")
        cal, cal_new = _register(
            registry, root, "cal", _png((80, 120, 80)),
            [E("Applications", selected=True),
             E("Calendar", selected=True, group="application-list"),
             E("Notifications", "shallow")], app_layout, "Applications")
        assert cal_new and cal != acc, "different selected app must split"

        bg_layout = {"nav_sidebar:r1", "content:r-bg"}
        bg1, _ = _register(
            registry, root, "bg1", _png((20, 80, 130)),
            [E("Background", selected=True),
             E("Choose Wallpaper", "shallow", group="wallpapers")],
            bg_layout, "Background")
        bg2, bg2_new = _register(
            registry, root, "bg2", _png((130, 80, 20)),
            [E("Background", selected=True),
             E("Choose Wallpaper", "shallow", group="wallpapers")],
            bg_layout, "Background")
        assert not bg2_new and bg2 == bg1, (
            "data-value/appearance change with same functions must merge")

        # Exact frames may receive entirely new segmentation ids; identity should
        # recover only while navigation and structured state remain unchanged.
        drift_registry = VisualStateRegistry()
        drift_shot = _png((25, 50, 75))
        drift_elements = [E("World", selected=True), E("Add city")]
        drift_a, _ = _register(
            drift_registry, root, "drift_a", drift_shot, drift_elements,
            {"tab_bar:r1", "content:r2"}, "World")
        drift_b, drift_b_new = _register(
            drift_registry, root, "drift_b", drift_shot, drift_elements,
            {"tab_bar:r2", "content:r4"}, "World")
        assert not drift_b_new and drift_b == drift_a
        assert drift_registry.region_set_of(drift_a) == {
            "tab_bar:r1", "content:r2", "tab_bar:r2", "content:r4"}

        split_registry = VisualStateRegistry()
        split_shot = _png((55, 65, 75))
        world, _ = _register(
            split_registry, root, "split_world", split_shot,
            [E("World", selected=True), E("Mode", stateful=True,
              state_key="mode", state_value="off",
              effect_scope="function_set")], {"a:r1", "b:r2"}, "Clock")
        alarms, alarms_new = _register(
            split_registry, root, "split_alarms", split_shot,
            [E("Alarms", selected=True), E("Mode", stateful=True,
              state_key="mode", state_value="off",
              effect_scope="function_set")], {"a:r3", "b:r4"}, "Clock")
        mode_on, mode_on_new = _register(
            split_registry, root, "split_mode", split_shot,
            [E("World", selected=True), E("Mode", stateful=True,
              state_key="mode", state_value="on",
              effect_scope="function_set")], {"a:r5", "b:r6"}, "Clock")
        assert alarms_new and alarms != world, "different selected tab must split"
        assert mode_on_new and mode_on != world, "different structured state must split"

        alarm_layout = {"tab_bar:r-clock", "content:r-alarm"}
        empty, _ = _register(
            registry, root, "alarm_empty", _png((30, 40, 60)),
            [E("Alarms", selected=True), E("Add alarm"),
             E("No alarms", "display")],
            alarm_layout, "Alarm Home")
        populated, populated_new = _register(
            registry, root, "alarm_has", _png((60, 40, 30)),
            [E("Alarms", selected=True), E("Add alarm"),
             E("08:00", group="alarm_item")],
            alarm_layout, "Alarm Home")
        assert populated_new and populated != empty
        assert registry.page_id_of(empty) == registry.page_id_of(populated)
        assert registry.variant_id_of(empty) != registry.variant_id_of(populated)

        # A generic VLM title must still distinguish sibling primary-navigation
        # destinations. The initial register call only has canonical button names;
        # the richer observation refines the semantic page mapping online.
        generic_a, _ = _register(
            registry, root, "settings_network", _png((45, 75, 105)),
            [E("Network", selected=True, region="nav_sidebar"),
             E("Wi-Fi", "shallow", region="content")],
            {"nav_sidebar:r-settings", "content:r-network"}, "Settings")
        registry.record_page_variant(
            generic_a, "Settings",
            elements=[E("Network", selected=True, region="nav_sidebar"),
                      E("Wi-Fi", "shallow", region="content")])
        generic_b, _ = _register(
            registry, root, "settings_bluetooth", _png((75, 105, 45)),
            [E("Bluetooth", selected=True, region="nav_sidebar"),
             E("Pair device", "shallow", region="content")],
            {"nav_sidebar:r-settings", "content:r-bluetooth"}, "Settings")
        registry.record_page_variant(
            generic_b, "Settings",
            elements=[E("Bluetooth", selected=True, region="nav_sidebar"),
                      E("Pair device", "shallow", region="content")])
        assert registry.page_id_of(generic_a) != registry.page_id_of(generic_b), (
            "selected primary navigation must disambiguate a generic page label")

        detail_a_facts = observed_variant_facts([
            E("08:00", "display"), E("Edit alarm"), E("Delete alarm")])
        detail_b_facts = observed_variant_facts([
            E("09:30", "display"), E("Edit alarm"), E("Delete alarm")])
        detail_page = compute_page_id("Alarm Detail")
        assert variant_signature(detail_a_facts) == variant_signature(detail_b_facts), (
            "instance data must not split a homogeneous detail variant")
        assert (compute_variant_id(detail_page, detail_a_facts)
                == compute_variant_id(detail_page, detail_b_facts))

        data_off = observed_variant_facts([
            E("Vibrate", "shallow", stateful=True, state_key="vibrate",
              state_value="off", effect_scope="data_only")])
        data_on = observed_variant_facts([
            E("Vibrate", "shallow", stateful=True, state_key="vibrate",
              state_value="on", effect_scope="data_only")])
        assert compute_variant_id(detail_page, data_off) == compute_variant_id(
            detail_page, data_on), "value-only toggles must not split variants"
        gate_off = observed_variant_facts([
            E("Bluetooth", "shallow", stateful=True, state_key="bluetooth",
              state_value="off", effect_scope="function_set")])
        gate_on = observed_variant_facts([
            E("Bluetooth", "shallow", stateful=True, state_key="bluetooth",
              state_value="on", effect_scope="function_set")])
        assert compute_variant_id(detail_page, gate_off) != compute_variant_id(
            detail_page, gate_on), "function-set gates must split variants"

        availability_registry = VisualStateRegistry()
        availability_registry._buttons["allowed"] = frozenset(
            signature_names([E("Camera", enabled=True)]))
        assert availability_registry._region_function_verdict(
            signature_names([
                E("Camera", enabled=False, requires_permission=True,
                  blocked_reason="permission required")]),
            "allowed",
        ) == "different", "explicit blocked/available states must split"
        assert compute_page_id("Alarm Detail") == compute_page_id("alarm_detail")
        assert compute_page_id("Alarm Detail") != compute_page_id("Alarm Editor")

        namespaced = VisualStateRegistry(namespace="clock")
        first_page, first_variant = namespaced.record_page_variant(
            "stable", "Alarm Home", elements=[E("Add alarm")])
        second_page, second_variant = namespaced.record_page_variant(
            "stable", "Alarm Home", elements=[E("Add alarm")],
            namespace="clock")
        assert (first_page, first_variant) == (second_page, second_variant), (
            "registry default and explicit app namespace must not oscillate")

        preliminary = VisualStateRegistry(namespace="clock")
        _page, top_variant = preliminary.record_page_variant(
            "scrolling", "Alarm Editor", elements=[E("Name", "input")])
        _page, full_variant = preliminary.record_page_variant(
            "scrolling", "Alarm Editor",
            elements=[E("Name", "input"), E("Save", "navigation")])
        assert top_variant != full_variant
        assert preliminary.variant_facts_of("scrolling")["functions"] == [
            "name", "save"]

        provisional = VisualStateRegistry(namespace="settings")
        provisional_id, _ = _register(
            provisional, root, "provisional", _png((12, 34, 56)),
            [E("Bluetooth", selected=True),
             E("Toggle Bluetooth", stateful=True,
               state_key="bluetooth_enabled", state_value="off")],
            {"nav_sidebar:r1", "content:r2"}, "Bluetooth")
        provisional_page = provisional.page_id_of(provisional_id)
        provisional_variant = provisional.variant_id_of(provisional_id)
        assert provisional.unregister_state(provisional_id) is True
        assert provisional.known_path(provisional_id) is None
        assert provisional.page_id_of(provisional_id) is None
        assert provisional.states_for_page(provisional_page) == ()
        assert provisional.states_for_variant(provisional_variant) == ()
        assert provisional.unregister_state(provisional_id) is False

    print("PASS page/variant identity: execution states split, semantic pages group")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
