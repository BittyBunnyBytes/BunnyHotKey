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
if os.environ.get("BHK_FOREIGN_EXTRA"):
    # more control kinds for x11_foreign_messages.ahk; added last so the ClassNNs above don't change
    w.set_focus_on_map(False)
    lv.get_selection().select_path(Gtk.TreePath(1))
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    scale.set_value(30)
    box.pack_start(scale, False, False, 0)
    prog = Gtk.ProgressBar()
    prog.set_fraction(0.4)
    box.pack_start(prog, False, False, 0)
    spin = Gtk.SpinButton.new_with_range(0, 50, 1)
    spin.set_value(7)
    box.pack_start(spin, False, False, 0)
    nb = Gtk.Notebook()
    for t in ("One", "Two", "Three"):
        nb.append_page(Gtk.Label(label="page " + t), Gtk.Label(label=t))
    box.pack_start(nb, False, False, 0)
    lb = Gtk.ListBox()
    for t in ("apple", "banana", "cherry"):
        lb.add(Gtk.Label(label=t))
    box.pack_start(lb, False, False, 0)
reset.connect("activate", lambda *_: status.set_text("menu reset"))
w.connect("destroy", Gtk.main_quit)
w.show_all()
Gtk.main()
