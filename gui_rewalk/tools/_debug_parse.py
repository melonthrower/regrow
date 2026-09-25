"""Debug: directly parse XML and check coordinates for Bold, New, Function Wizard."""
import requests, ast, xml.etree.ElementTree as ET

VM = "http://<PRIVATE_HOST>:5000"
r = requests.get(f"{VM}/accessibility", timeout=30)
xml_str = r.json()["AT"]
root = ET.fromstring(xml_str)

comp_ns = "https://accessibility.ubuntu.example.org/ns/component"

# Walk entire tree to find specific elements
targets = {"Bold", "New", "Function Wizard", "File", "Sheet 1 of 1"}
found = []

for node in root.iter():
    name = node.get("name", "")
    text = node.text or ""
    if name in targets or text in targets:
        coord_raw = node.get(f"{{{comp_ns}}}screencoord", "NONE")
        size_raw = node.get(f"{{{comp_ns}}}size", "NONE")
        print(f"<{node.tag}> name=\"{name}\" text=\"{text}\"")
        print(f"  raw screencoord attr = {coord_raw!r}")
        print(f"  raw size attr        = {size_raw!r}")
        if coord_raw != "NONE":
            try:
                val = ast.literal_eval(coord_raw)
                print(f"  parsed coord = {val}")
            except:
                print(f"  PARSE FAILED")
        print()
