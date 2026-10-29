"""GTK3 dialog helper process: reads one JSON request on stdin, writes the answer as JSON on stdout."""
import json
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

ICONS = {"error": "dialog-error", "warning": "dialog-warning", "question": "dialog-question",
         "info": "dialog-information"}


def message(req):
    buttons = req["buttons"]
    dlg = Gtk.Dialog(title=req["title"])
    dlg.set_keep_above(True)
    dlg.set_position(Gtk.WindowPosition.CENTER)
    row = Gtk.Box(spacing=12)
    row.set_border_width(14)
    if req.get("icon"):
        row.pack_start(Gtk.Image.new_from_icon_name(ICONS.get(req["icon"], "dialog-information"), Gtk.IconSize.DIALOG),
                       False, False, 0)
    label = Gtk.Label(label=req["text"], xalign=0, selectable=True)
    label.set_line_wrap(True)
    label.set_max_width_chars(80)
    row.pack_start(label, True, True, 0)
    dlg.get_content_area().pack_start(row, True, True, 0)
    for i, b in enumerate(buttons):
        dlg.add_button("Try Again" if b == "TryAgain" else b, i)
    dlg.set_default_response(max(0, min(req.get("default", 1) - 1, len(buttons) - 1)))
    timeout = req.get("timeout")
    if timeout:
        GLib.timeout_add(int(timeout * 1000), lambda: dlg.response(-100) or False)
    dlg.show_all()
    resp = dlg.run()
    if resp == -100:
        return {"button": "Timeout"}
    if 0 <= resp < len(buttons):
        return {"button": buttons[resp]}
    return {"button": "Cancel" if "Cancel" in buttons else buttons[-1]}


def entry(req):
    dlg = Gtk.Dialog(title=req["title"])
    dlg.set_keep_above(True)
    dlg.set_position(Gtk.WindowPosition.CENTER)
    box = dlg.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    box.pack_start(Gtk.Label(label=req["prompt"], xalign=0), False, False, 0)
    field = Gtk.Entry(text=req.get("default", ""))
    field.set_visibility(not req.get("password"))
    field.set_activates_default(True)
    box.pack_start(field, False, False, 0)
    dlg.add_button("OK", 1)
    dlg.add_button("Cancel", 0)
    dlg.set_default_response(1)
    timeout = req.get("timeout")
    if timeout:
        GLib.timeout_add(int(timeout * 1000), lambda: dlg.response(-100) or False)
    dlg.show_all()
    resp = dlg.run()
    result = "OK" if resp == 1 else "Timeout" if resp == -100 else "Cancel"
    return {"value": field.get_text(), "result": result}


def choose_file(req):
    mode = req.get("mode", "open")
    action = {"save": Gtk.FileChooserAction.SAVE, "dir": Gtk.FileChooserAction.SELECT_FOLDER}.get(
        mode, Gtk.FileChooserAction.OPEN)
    dlg = Gtk.FileChooserDialog(title=req.get("title", "Select"), action=action)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
    dlg.set_select_multiple(mode == "multi")
    start = req.get("start")
    if start:
        import os
        if os.path.isdir(start):
            dlg.set_current_folder(start)
        else:
            dlg.set_filename(start)
    resp = dlg.run()
    paths = dlg.get_filenames() if resp == Gtk.ResponseType.OK else []
    return {"paths": paths}


def main():
    req = json.loads(sys.stdin.read())
    kind = req["kind"]
    out = message(req) if kind == "message" else entry(req) if kind == "entry" else choose_file(req)
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
