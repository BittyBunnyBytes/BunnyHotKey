"""A small GTK application used as a *foreign* program by the AT-SPI control tests (it is not a BHK Gui)."""
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

w = Gtk.Window(title="BHK Foreign App")
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
w.add(box)
bar = Gtk.MenuBar()
filem = Gtk.MenuItem(label="File")
sub = Gtk.Menu()
reset = Gtk.MenuItem(label="Reset")
sub.append(reset)
filem.set_submenu(sub)
bar.append(filem)
box.pack_start(bar, False, False, 0)
box.pack_start(Gtk.Label(label="Name:"), False, False, 0)
entry = Gtk.Entry(text="hello")
if os.environ.get("BHK_FOREIGN_LOG"):
    # every change to the entry, in order, for tests that check what reached the app and when
    entry.connect("changed", lambda e: open(os.environ["BHK_FOREIGN_LOG"], "a").write(e.get_text() + "\n"))
box.pack_start(entry, False, False, 0)
chk = Gtk.CheckButton(label="Enable feature")
box.pack_start(chk, False, False, 0)
combo = Gtk.ComboBoxText()
for t in ("red", "green", "blue"):
    combo.append_text(t)
combo.set_active(1)
box.pack_start(combo, False, False, 0)
tv = Gtk.TextView()
tv.get_buffer().set_text("line one\nline two\nline three")
box.pack_start(tv, False, False, 0)
store = Gtk.ListStore(str, str)
for r in (("a.txt", "3"), ("b.txt", "20")):
    store.append(r)
lv = Gtk.TreeView(model=store)
for i, t in enumerate(("Name", "Size")):
    lv.append_column(Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i))
box.pack_start(lv, False, False, 0)
status = Gtk.Label(label="")
btn = Gtk.Button(label="Go")
btn.connect("clicked", lambda *_: status.set_text("clicked " + entry.get_text()))
box.pack_start(btn, False, False, 0)
sb = Gtk.Statusbar()
sb.push(0, "Ready")
box.pack_start(sb, False, False, 0)
box.pack_start(status, False, False, 0)
reset.connect("activate", lambda *_: status.set_text("menu reset"))
w.connect("destroy", Gtk.main_quit)
w.show_all()
Gtk.main()
