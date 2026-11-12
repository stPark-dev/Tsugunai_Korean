"""Send key presses to the PCSX2 window via XTEST and take screenshots."""
import sys, time, subprocess
from Xlib import X, XK, display
from Xlib.ext import xtest

WIN_NAME = 'pcsx2-qt'
DISPLAY = ':99'  # virtual X server so the user's desktop is never touched

def _focus(d):
    root = d.screen().root
    def walk(w):
        try:
            cls = w.get_wm_class()
            name = w.get_wm_name()
        except Exception:
            cls = name = None
        if cls and 'pcsx2-qt' in cls and name and name not in ('pcsx2-qt',) and w.get_geometry().width > 200:
            return w
        for c in w.query_tree().children:
            r = walk(c)
            if r: return r
    w = walk(root)
    if w:
        w.set_input_focus(X.RevertToParent, X.CurrentTime); w.raise_window(); d.sync()
    return w

def press(keys, hold=0.12, gap=0.35):
    d = display.Display(DISPLAY)
    _focus(d); time.sleep(0.2)
    for k in keys:
        kc = d.keysym_to_keycode(XK.string_to_keysym(k))
        xtest.fake_input(d, X.KeyPress, kc); d.sync(); time.sleep(hold)
        xtest.fake_input(d, X.KeyRelease, kc); d.sync(); time.sleep(gap)

def shot(path):
    out = subprocess.run(['bash', '-c', "DISPLAY=:99 xwininfo -root -tree | grep '\"pcsx2-qt\": (\"pcsx2-qt\" \"pcsx2-qt\")' | grep -v ' 1x1' | head -1 | awk '{print $1}'"], capture_output=True, text=True).stdout.strip()
    subprocess.run(['import', '-display', DISPLAY, '-window', out, path], check=True)

if __name__ == '__main__':
    if sys.argv[1] == 'press': press(sys.argv[2:])
    elif sys.argv[1] == 'shot': shot(sys.argv[2])
