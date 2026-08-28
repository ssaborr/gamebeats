from pywinauto import Desktop
import json, time, sys

# Pause a few seconds to let you hover the element before running
print("Switch to Spotify and hover the playlist tile now (5s)...")
time.sleep(5)

desktop = Desktop(backend="uia")
win = desktop.window(title_re=".*Spotify.*")
win.wait("visible", timeout=5)

def serialize(elem):
    ei = elem.element_info
    try:
        rect = elem.rectangle()
        rect = {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}
    except Exception:
        rect = None
    return {
        "name": getattr(ei, "name", None),
        "help_text": getattr(ei, "help_text", None),
        "automation_id": getattr(ei, "automation_id", None),
        "control_type": getattr(ei, "control_type", None),
        "class_name": getattr(ei, "class_name", None),
        "rectangle": rect,
    }

def walk(elem, depth=0, max_depth=6):
    out = {"self": serialize(elem), "children": []}
    if depth >= max_depth:
        return out
    try:
        for c in elem.children():
            out["children"].append(walk(c, depth+1, max_depth))
    except Exception:
        pass
    return out

tree = walk(win)
with open("spotify_ui_dump.json", "w", encoding="utf-8") as f:
    json.dump(tree, f, indent=2, ensure_ascii=False)
print("Dump written to spotify_ui_dump.json")

# Also enumerate all Button controls at the top level and save concise info
try:
    buttons = []
    for b in win.descendants(control_type="Button"):
        ei = b.element_info
        try:
            r = b.rectangle()
            rect = {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom}
        except Exception:
            rect = None
        buttons.append({
            "name": getattr(ei, "name", None),
            "help_text": getattr(ei, "help_text", None),
            "automation_id": getattr(ei, "automation_id", None),
            "class_name": getattr(ei, "class_name", None),
            "control_type": getattr(ei, "control_type", None),
            "rectangle": rect,
        })
    with open("spotify_buttons.json", "w", encoding="utf-8") as f:
        json.dump(buttons, f, indent=2, ensure_ascii=False)
    print(f"Buttons written to spotify_buttons.json ({len(buttons)} items)")
except Exception as e:
    print("Failed to enumerate buttons:", e)