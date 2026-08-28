from pywinauto import Desktop, mouse
import json, math, time, sys
import ctypes
from ctypes import wintypes

# Win32 message constants
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
BM_CLICK = 0x00F5


def center(rect):
    return ((rect['left'] + rect['right']) // 2, (rect['top'] + rect['bottom']) // 2)


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def click_rect_center(rect):
    cx, cy = center(rect)
    print(f"Clicking absolute at ({cx},{cy})")
    # This is an absolute cursor-based click (moves user cursor). Keep for explicit fallback only.
    mouse.click(coords=(cx, cy))


def click_hwnd_no_cursor(hwnd, rect):
    # Send messages to the control's window at the center point — does not move the cursor.
    try:
        cx = (rect['left'] + rect['right']) // 2
        cy = (rect['top'] + rect['bottom']) // 2
        # Convert screen coords to client coords for the target hwnd
        pt = wintypes.POINT(cx, cy)
        if not ctypes.windll.user32.ScreenToClient(int(hwnd), ctypes.byref(pt)):
            # ScreenToClient can fail for some hwnds; still compute relative as fallback
            x_rel = int(cx - rect['left'])
            y_rel = int(cy - rect['top'])
        else:
            x_rel = int(pt.x)
            y_rel = int(pt.y)

        lparam = (y_rel << 16) | (x_rel & 0xffff)

        # Try BM_CLICK for standard BUTTON controls first
        try:
            res = ctypes.windll.user32.SendMessageW(int(hwnd), BM_CLICK, 0, 0)
            if res is not None:
                print(f"Sent BM_CLICK to hwnd {hwnd}")
                return True
        except Exception:
            pass

        # Prefer PostMessage (async, won't block caller)
        try:
            ctypes.windll.user32.PostMessageW(int(hwnd), WM_LBUTTONDOWN, 1, lparam)
            time.sleep(0.02)
            ctypes.windll.user32.PostMessageW(int(hwnd), WM_LBUTTONUP, 0, lparam)
            print(f"Posted WM_LBUTTONDOWN/UP to hwnd {hwnd} at rel ({x_rel},{y_rel})")
            return True
        except Exception:
            # Fallback to SendMessage if PostMessage fails
            try:
                ctypes.windll.user32.SendMessageW(int(hwnd), WM_LBUTTONDOWN, 1, lparam)
                time.sleep(0.02)
                ctypes.windll.user32.SendMessageW(int(hwnd), WM_LBUTTONUP, 0, lparam)
                print(f"Sent WM_LBUTTONDOWN/UP to hwnd {hwnd} at rel ({x_rel},{y_rel})")
                return True
            except Exception:
                # As a last-resort fallback, post messages using absolute screen coordinates encoded in lParam
                try:
                    if click_hwnd_postraw(int(hwnd), cx, cy):
                        return True
                except Exception:
                    pass
                raise
    except Exception as e:
        print('click_hwnd_no_cursor failed:', e)
        return False


def click_hwnd_postraw(hwnd, x, y):
    """Post WM_LBUTTON messages using absolute screen coords encoded into lParam.

    Some apps respond to messages where lParam encodes screen coordinates instead
    of client coordinates — try that when client-based posting fails.
    """
    try:
        lparam = (int(y) << 16) | (int(x) & 0xffff)
        ctypes.windll.user32.PostMessageW(int(hwnd), WM_LBUTTONDOWN, 1, lparam)
        time.sleep(0.02)
        ctypes.windll.user32.PostMessageW(int(hwnd), WM_LBUTTONUP, 0, lparam)
        print(f"Posted raw-screen WM_LBUTTONDOWN/UP to hwnd {hwnd} at screen ({x},{y})")
        return True
    except Exception as e:
        print('click_hwnd_postraw failed:', e)
        return False


def click_by_suggestion(win, data, dry_run=False):
    sugg = data.get('suggestion') or {}
    elem = data.get('element') or {}
    rect = elem.get('rectangle') if elem else None
    control_type = sugg.get('control_type')
    class_name = sugg.get('class_name')

    # 1) automation id
    if sugg.get('by') == 'automation_id' and sugg.get('value'):
        try:
            print('Trying automation_id...')
            ctrl = win.child_window(auto_id=sugg['value'], control_type=control_type).wrapper_object()
            print('Found control by automation_id:', ctrl)
            if not dry_run:
                try:
                    ctrl.invoke()
                    print('Invoked control via UIA InvokePattern')
                    return True
                except Exception:
                    hwnd = getattr(ctrl, 'handle', None) or getattr(ctrl.element_info, 'native_window', None)
                    try:
                        r = ctrl.rectangle()
                        rect_obj = {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom}
                    except Exception:
                        rect_obj = None
                    if hwnd and rect_obj:
                        if click_hwnd_no_cursor(hwnd, rect_obj):
                            return True
                    ctrl.click_input()
                    return True
        except Exception as e:
            print('automation_id lookup failed:', e)

    # 2) control_type + name
    if sugg.get('by') == 'control_type_and_name' and 'name' in sugg:
        try:
            print('Trying control_type+name...')
            ctrl = win.child_window(title=sugg['name'], control_type=control_type).wrapper_object()
            print('Found control by name:', ctrl)
            if not dry_run:
                try:
                    ctrl.invoke()
                    print('Invoked control via UIA InvokePattern')
                    return True
                except Exception:
                    hwnd = getattr(ctrl, 'handle', None) or getattr(ctrl.element_info, 'native_window', None)
                    try:
                        r = ctrl.rectangle()
                        rect_obj = {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom}
                    except Exception:
                        rect_obj = None
                    if hwnd and rect_obj:
                        if click_hwnd_no_cursor(hwnd, rect_obj):
                            return True
                    ctrl.click_input()
                    return True
        except Exception as e:
            print('name lookup failed:', e)

    # 3) class + control_type — search descendants for matching element_info
    if sugg.get('by') == 'class_and_control_type' and (class_name or control_type):
        print('Searching descendants for class+control_type...')
        candidates = []
        try:
            for c in win.descendants():
                try:
                    ei = c.element_info
                    c_class = getattr(ei, 'class_name', None)
                    c_type = getattr(ei, 'control_type', None)
                    if ((not class_name or c_class == class_name) and (not control_type or c_type == control_type)):
                        try:
                            r = c.rectangle()
                            candidates.append((c, {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom}))
                        except Exception:
                            candidates.append((c, None))
                except Exception:
                    pass
        except Exception as e:
            print('descendants() failed:', e)

        if candidates:
            print(f'Found {len(candidates)} candidate(s)')
            # prefer candidate containing the recorded cursor / rectangle center
            target = None
            if rect:
                target_point = center(rect)
                best = None
                for c, r in candidates:
                    if r:
                        if r['left'] <= target_point[0] <= r['right'] and r['top'] <= target_point[1] <= r['bottom']:
                            target = c
                            break
                        else:
                            d = distance(center(r), target_point)
                            if best is None or d < best[0]:
                                best = (d, c)
                if not target and best:
                    target = best[1]
            else:
                # choose smallest area candidate
                best = None
                for c, r in candidates:
                    if r:
                        area = (r['right']-r['left'])*(r['bottom']-r['top'])
                        if best is None or area < best[0]:
                            best = (area, c)
                if best:
                    target = best[1]

            if target:
                try:
                    w = target.wrapper_object()
                    print('Clicking candidate (prefer Invoke):', target)
                    if not dry_run:
                        # Prefer InvokePattern (doesn't move cursor)
                        try:
                            w.invoke()
                            print('Invoked element via UIA InvokePattern')
                            return True
                        except Exception:
                            # If no invoke available, try HWND message-based click
                            hwnd = getattr(w, 'handle', None) or getattr(w.element_info, 'native_window', None)
                            try:
                                r = w.rectangle()
                                rect_obj = {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom}
                            except Exception:
                                rect_obj = None

                            if hwnd and rect_obj:
                                ok = click_hwnd_no_cursor(hwnd, rect_obj)
                                if ok:
                                    return True

                            # Last resort: fall back to a physical synthetic click (moves cursor)
                            try:
                                w.click_input()
                                return True
                            except Exception as e:
                                print('Failed to click candidate (last-resort):', e)
                except Exception as e:
                    print('Failed to prepare candidate for click:', e)

    # fallback: click recorded rectangle center or window-relative
    if rect:
        try:
            click_rect_center(rect)
            return True
        except Exception as e:
            print('Fallback click_rect_center failed:', e)

    print('No suitable target found')
    return False


def parse_selector(selector: str):
    # supports simple selectors: button.play, button[class*=legacy], button[role=Play]
    sel = selector.strip()
    result = {'control_type': None, 'class_contains': None, 'role': None}
    if sel.startswith('button'):
        result['control_type'] = 'Button'
        rest = sel[len('button'):]
        if rest.startswith('.'):
            # .play
            result['class_contains'] = rest[1:]
        elif rest.startswith('[') and rest.endswith(']'):
            inner = rest[1:-1]
            if inner.startswith('class*='):
                result['class_contains'] = inner.split('=',1)[1]
            elif inner.startswith('role='):
                result['role'] = inner.split('=',1)[1]
    return result


def click_by_selector(win, selector, dry_run=False):
    s = parse_selector(selector)
    print('Selector parsed as:', s)
    candidates = []
    try:
        for c in win.descendants():
            try:
                ei = c.element_info
                ctype = getattr(ei, 'control_type', None)
                cname = getattr(ei, 'class_name', '') or ''
                name = getattr(ei, 'name', '') or ''
                if s['control_type'] and ctype != s['control_type']:
                    continue
                if s['class_contains'] and s['class_contains'].lower() not in cname.lower():
                    continue
                if s['role'] and s['role'].lower() not in name.lower():
                    continue
                candidates.append((c, cname, name))
            except Exception:
                pass
    except Exception as e:
        print('descendants() failed for selector:', e)

    if not candidates:
        print('No candidates found for selector')
        return False

    # Prefer smallest area or exact name match
    target = None
    best = None
    for c, cname, name in candidates:
        try:
            r = c.rectangle()
            area = (r.right - r.left) * (r.bottom - r.top)
            if best is None or area < best[0]:
                best = (area, c, {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom})
        except Exception:
            if target is None:
                target = c

    if best:
        target = best[1]
        rect_obj = best[2]
    else:
        rect_obj = None

    try:
        w = target.wrapper_object()
        if not dry_run:
            try:
                w.invoke()
                print('Invoked element via UIA InvokePattern (selector)')
                return True
            except Exception:
                hwnd = getattr(w, 'handle', None) or getattr(w.element_info, 'native_window', None)
                if hwnd and rect_obj:
                    ok = click_hwnd_no_cursor(hwnd, rect_obj)
                    if ok:
                        return True
                try:
                    w.click_input()
                    return True
                except Exception as e:
                    print('Final click_input failed for selector:', e)
                    return False
        else:
            print('Dry-run: would click', target)
            return True
    except Exception as e:
        print('Failed to operate on selected element:', e)
        return False


def main(dry_run=False, selector=None):
    try:
        with open('last_spotify_click.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print('Failed to load last_spotify_click.json:', e)
        return 1

    win_re = data.get('suggestion', {}).get('window_title_re', '.*Spotify.*')
    desktop = Desktop(backend='uia')
    try:
        win = desktop.window(title_re=win_re)
        win.wait('visible', timeout=2)
    except Exception as e:
        print('Spotify window not found:', e)
        return 2

    # If selector provided on CLI, use selector-based click
    if selector:
        ok = click_by_selector(win, selector, dry_run=dry_run)
    else:
        ok = click_by_suggestion(win, data, dry_run=dry_run)
    if ok:
        print('Click attempt finished')
        return 0
    else:
        print('Click attempt failed')
        return 3


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    selector = None
    if '--selector' in sys.argv:
        i = sys.argv.index('--selector')
        if i + 1 < len(sys.argv):
            selector = sys.argv[i+1]
    sys.exit(main(dry_run=dry, selector=selector))
