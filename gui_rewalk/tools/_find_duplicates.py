"""Find all occurrences of key elements in raw XML to check for coordinate duplicates."""
import requests, re

VM = "http://<PRIVATE_HOST>:5000"
r = requests.get(f"{VM}/accessibility", timeout=30)
xml = r.json()["AT"]

# Search for all "Bold" button occurrences
for name in ["Bold", "New", "Function Wizard", "Formula"]:
    print(f"\n=== All '{name}' occurrences ===")
    # Find patterns like: name="Bold" ... cp:screencoord="(x, y)" ... cp:size="(w, h)"
    pattern = rf'<[^>]*name="{re.escape(name)}"[^>]*>'
    matches = list(re.finditer(pattern, xml))
    for i, m in enumerate(matches):
        tag_str = m.group(0)
        # Extract tag name
        tag_match = re.match(r'<(\S+)', tag_str)
        tag = tag_match.group(1) if tag_match else "?"
        # Extract coord
        coord_match = re.search(r'cp:screencoord="([^"]*)"', tag_str)
        coord = coord_match.group(1) if coord_match else "NO COORD"
        # Extract size
        size_match = re.search(r'cp:size="([^"]*)"', tag_str)
        size = size_match.group(1) if size_match else "NO SIZE"
        print(f"  [{i}] <{tag}> coord={coord} size={size}")
        # Show context around this match (parent tags)
        start = max(0, m.start() - 200)
        context = xml[start:m.start()]
        # Find last few opening tags
        parent_tags = re.findall(r'<(\w[\w-]*)[^>]*name="([^"]*)"', context[-300:])
        if parent_tags:
            parents = " > ".join(f"{t}:{n}" for t, n in parent_tags[-3:])
            print(f"       parents: ...{parents}")
