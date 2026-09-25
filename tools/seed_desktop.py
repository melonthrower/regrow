"""Seed the OSWorld desktop VM with realistic user data via its :5000 controller
(POST /execute). Mirrors the mobile seed: documents (txt/md/pdf/xlsx via
LibreOffice), images (ImageMagick), a VS Code project, Desktop/Downloads files,
and Chrome bookmarks — so Files/Nautilus, LibreOffice, VS Code, the image viewer
and the browser all open to data instead of an empty home.

Run on js1 against the seed container's mapped port:
  python tools/seed_desktop.py http://localhost:5099
"""
import sys

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5099"


def run(cmd, timeout=180):
    r = requests.post(BASE + "/execute", json={"command": cmd, "shell": True},
                      timeout=timeout)
    d = r.json()
    return d.get("returncode"), d.get("output", ""), d.get("error", "")


SEED = r"""
mkdir -p ~/Documents ~/Desktop ~/Downloads ~/Pictures ~/Projects/todo-app

# --- Documents (plain text + markdown) ---
printf 'Team Sync - June 2026\n- Ship desktop seed\n- Review graph traversal\n- Plan Q3 roadmap\n' > ~/Documents/meeting_notes.txt
printf '# Project Plan\n\n## Phase 1\nTrustworthy state graph\n\n## Phase 2\nApp capability graph\n' > ~/Documents/project_plan.md
printf 'Groceries: milk, eggs, bread, coffee\nCall the dentist\nBook flights for the trip\n' > ~/Documents/todo_list.txt

# --- LibreOffice -> a PDF report and an XLSX budget ---
printf 'Quarterly Report 2026\n\nRevenue up 12 percent YoY. Costs flat. Hiring 3 engineers next quarter.\n' > /tmp/report.txt
soffice --headless --convert-to pdf --outdir ~/Documents /tmp/report.txt >/dev/null 2>&1 || true
printf 'Item,Qty,Price\nApples,5,2.50\nBread,2,3.00\nMilk,1,1.20\nCoffee,1,8.90\n' > /tmp/budget.csv
soffice --headless --convert-to xlsx --outdir ~/Documents /tmp/budget.csv >/dev/null 2>&1 || true

# --- Desktop / Downloads ---
printf '1. Seed the desktop VM\n2. Re-run traversal\n3. Compare node counts\n' > ~/Desktop/todo.txt
printf 'Invoice - March 2026 - $1,240.00\n' > ~/Downloads/invoice_march.txt

# --- Pictures (ImageMagick labelled jpgs) ---
i=0
for n in vacation_beach birthday_party mountain_trip city_skyline family_photo; do
  c=$(printf '%s' steelblue seagreen indianred slateblue darkorange | cut -c1)
  convert -size 1024x768 "xc:$(echo 'steelblue seagreen indianred slateblue darkorange' | tr ' ' '\n' | sed -n "$((i+1))p")" -gravity center -pointsize 52 -fill white -annotate +0+0 "$n" ~/Pictures/$n.jpg 2>/dev/null || true
  i=$((i+1))
done

# --- VS Code project ---
printf 'def add_task(tasks, t):\n    tasks.append(t)\n    return tasks\n\n\nif __name__ == "__main__":\n    print(add_task([], "buy milk"))\n' > ~/Projects/todo-app/main.py
printf '# Todo App\n\nA simple command-line todo manager.\n' > ~/Projects/todo-app/README.md
printf '{"name": "todo-app", "version": "1.0.0"}\n' > ~/Projects/todo-app/package.json

# --- Chrome bookmarks (file-based) ---
mkdir -p ~/.config/google-chrome/Default
cat > ~/.config/google-chrome/Default/Bookmarks <<'BM'
{"checksum":"","roots":{"bookmark_bar":{"children":[{"name":"GitHub","type":"url","url":"https://github.com"},{"name":"Wikipedia","type":"url","url":"https://wikipedia.org"},{"name":"Stack Overflow","type":"url","url":"https://stackoverflow.com"},{"name":"Hacker News","type":"url","url":"https://news.ycombinator.com"}],"date_added":"0","name":"Bookmarks bar","type":"folder"},"other":{"children":[],"name":"Other bookmarks","type":"folder"},"synced":{"children":[],"name":"Mobile bookmarks","type":"folder"}},"version":1}
BM

sync
echo SEED_OK
echo "--- Documents ---"; ls ~/Documents
echo "--- Pictures ---"; ls ~/Pictures
echo "--- Projects/todo-app ---"; ls ~/Projects/todo-app
echo "--- Desktop ---"; ls ~/Desktop
"""

print("seeding desktop ...")
rc, out, err = run(SEED)
print("returncode:", rc)
print(out)
if err.strip():
    print("STDERR:", err[-400:])
