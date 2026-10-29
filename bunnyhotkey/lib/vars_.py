"""Built-in variables (lib/vars.cpp, BIV_* in script2.cpp)."""
from __future__ import annotations

import datetime as dt
import getpass
import os
import platform
import socket
import sys
import time

from .. import objects as O
from ..objects import AhkArray, throw
from ..values import UNSET, to_bool
from .files import shell_folder


def register_vars(rt):
    from ..runtime import VERSION
    from . import clipboard, input_, window
    from .datetime_ import a_now

    V = rt.bivars

    def ro(name, fn):
        V[name.lower()] = (fn, None)

    def rw(name, get, set_):
        V[name.lower()] = (get, set_)

    sp = rt.script_path

    def script_dir():
        return os.path.dirname(sp) if sp != "*" else os.getcwd()

    ro("A_ScriptDir", script_dir)
    ro("A_ScriptName", lambda: os.path.basename(sp) if sp != "*" else "*")
    rw("A_ScriptName", lambda: getattr(rt, "script_name_override", None) or (os.path.basename(sp) if sp != "*" else "*"),
       lambda v: setattr(rt, "script_name_override", rt.to_str(v)))
    ro("A_ScriptFullPath", lambda: sp)
    ro("A_ScriptHwnd", lambda: getattr(rt, "script_hwnd", 0))
    ro("A_LineNumber", lambda: rt.line)
    ro("A_LineFile", lambda: rt.file)
    ro("A_ThisFunc", lambda: rt.call_stack[-1].name if rt.call_stack else "")
    ro("A_AhkVersion", lambda: getattr(rt, "ahk_version", VERSION))
    ro("A_AhkPath", lambda: getattr(rt, "ahk_path", sys.argv[0]))
    ro("A_IsCompiled", lambda: "")
    rw("A_WorkingDir", lambda: os.getcwd(), lambda v: _chdir(rt, v))
    rw("A_InitialWorkingDir", lambda: rt.initial_cwd, None)
    ro("A_Args", lambda: rt.args_array)
    ro("A_IsAdmin", lambda: int(os.geteuid() == 0))
    ro("A_PtrSize", lambda: 8)
    ro("A_Is64bitOS", lambda: 1)
    ro("A_IsUnicode", lambda: 1)
    ro("A_OSVersion", lambda: "10.0.19045")
    ro("A_ComputerName", lambda: socket.gethostname())
    ro("A_UserName", lambda: getpass.getuser())
    ro("A_Language", lambda: "0409")
    ro("A_ComSpec", lambda: "/bin/sh")
    ro("A_Temp", lambda: shell_folder("temp"))
    ro("A_WinDir", lambda: os.path.join(rt.prefix_root(), "drive_c", "windows"))
    ro("A_ProgramFiles", lambda: os.path.join(rt.prefix_root(), "drive_c", "Program Files"))
    ro("A_AppData", lambda: shell_folder("appdata"))
    ro("A_AppDataCommon", lambda: "/usr/share")
    ro("A_Desktop", lambda: shell_folder("desktop"))
    ro("A_DesktopCommon", lambda: shell_folder("desktop"))
    ro("A_MyDocuments", lambda: shell_folder("documents"))
    ro("A_StartMenu", lambda: shell_folder("startmenu"))
    ro("A_StartMenuCommon", lambda: "/usr/share/applications")
    ro("A_Programs", lambda: shell_folder("programs"))
    ro("A_ProgramsCommon", lambda: "/usr/share/applications")
    ro("A_Startup", lambda: shell_folder("startup"))
    ro("A_StartupCommon", lambda: "/etc/xdg/autostart")
    ro("A_Space", lambda: " ")
    ro("A_Tab", lambda: "\t")

    # time
    def now_part(fmt, utc=False):
        return lambda: (dt.datetime.now(dt.timezone.utc) if utc else dt.datetime.now()).strftime(fmt)
    ro("A_Now", lambda: a_now())
    ro("A_NowUTC", lambda: a_now(True))
    for name, fmt in (("A_YYYY", "%Y"), ("A_Year", "%Y"), ("A_MM", "%m"), ("A_Mon", "%m"), ("A_DD", "%d"),
                      ("A_MDay", "%d"), ("A_MMMM", "%B"), ("A_MMM", "%b"), ("A_DDDD", "%A"), ("A_DDD", "%a"),
                      ("A_Hour", "%H"), ("A_Min", "%M"), ("A_Sec", "%S")):
        ro(name, now_part(fmt))
    ro("A_WDay", lambda: (dt.datetime.now().weekday() + 1) % 7 + 1)
    ro("A_YDay", lambda: dt.datetime.now().timetuple().tm_yday)
    ro("A_YWeek", lambda: "%04d%02d" % dt.datetime.now().isocalendar()[:2])
    ro("A_MSec", lambda: "%03d" % (dt.datetime.now().microsecond // 1000))
    ro("A_TickCount", lambda: int(time.monotonic() * 1000))

    # thread / loop
    ro("A_Index", lambda: rt.thread.loop.index)
    rw("A_Index", lambda: rt.thread.loop.index, lambda v: setattr(rt.thread.loop, "index", rt.to_int(v)))
    ro("A_LoopField", lambda: _loopfield(rt))
    ro("A_LoopReadLine", lambda: _loopread(rt))
    for attr in ("Name", "Ext", "Path", "FullPath", "ShortPath", "ShortName", "Dir", "TimeModified", "TimeCreated",
                 "TimeAccessed", "Attrib", "Size", "SizeKB", "SizeMB"):
        ro("A_LoopFile" + attr, (lambda a: lambda: _loopfile(rt, a))(attr))
    for attr in ("Name", "Type", "Key", "TimeModified"):
        ro("A_LoopReg" + attr, (lambda a: lambda: _loopreg(rt, a))(attr))
    ro("A_ThisHotkey", lambda: rt.this_hotkey)
    ro("A_PriorHotkey", lambda: rt.prior_hotkey)
    ro("A_TimeSinceThisHotkey", lambda: int((time.monotonic() - rt.this_hotkey_time) * 1000) if rt.this_hotkey else -1)
    ro("A_TimeSincePriorHotkey", lambda: int((time.monotonic() - rt.prior_hotkey_time) * 1000) if rt.prior_hotkey else -1)
    ro("A_EndChar", lambda: rt.end_char)
    ro("A_PriorKey", lambda: rt.prior_key)
    rw("A_EventInfo", lambda: rt.thread.event_info, lambda v: setattr(rt.thread, "event_info", v))
    ro("A_IsCritical", lambda: rt.thread.settings.critical if rt.thread.is_critical else 0)
    ro("A_IsPaused", lambda: int(rt.paused))
    ro("A_IsSuspended", lambda: int(rt.suspended))
    ro("A_TimeIdle", lambda: input_.time_idle())
    ro("A_TimeIdlePhysical", lambda: input_.time_idle())
    ro("A_TimeIdleKeyboard", lambda: input_.time_idle())
    ro("A_TimeIdleMouse", lambda: input_.time_idle())
    rw("A_LastError", lambda: rt.last_error, lambda v: setattr(rt, "last_error", rt.to_int(v)))

    # settings
    st = lambda: rt.thread.settings
    rw("A_TitleMatchMode", lambda: st().title_match_mode, lambda v: _call(rt, "SetTitleMatchMode", v))
    rw("A_TitleMatchModeSpeed", lambda: st().title_match_speed, lambda v: _call(rt, "SetTitleMatchMode", v))
    rw("A_DetectHiddenWindows", lambda: int(st().detect_hidden_windows), lambda v: setattr(st(), "detect_hidden_windows", to_bool(v)))
    rw("A_DetectHiddenText", lambda: int(st().detect_hidden_text), lambda v: setattr(st(), "detect_hidden_text", to_bool(v)))
    rw("A_SendMode", lambda: st().send_mode, lambda v: _call(rt, "SendMode", v))
    rw("A_SendLevel", lambda: st().send_level, lambda v: setattr(st(), "send_level", rt.to_int(v)))
    rw("A_KeyDelay", lambda: st().key_delay, lambda v: setattr(st(), "key_delay", rt.to_int(v)))
    rw("A_KeyDuration", lambda: st().key_duration, lambda v: setattr(st(), "key_duration", rt.to_int(v)))
    rw("A_KeyDelayPlay", lambda: st().key_delay_play, lambda v: setattr(st(), "key_delay_play", rt.to_int(v)))
    rw("A_KeyDurationPlay", lambda: st().key_duration_play, lambda v: setattr(st(), "key_duration_play", rt.to_int(v)))
    rw("A_MouseDelay", lambda: st().mouse_delay, lambda v: setattr(st(), "mouse_delay", rt.to_int(v)))
    rw("A_MouseDelayPlay", lambda: st().mouse_delay_play, lambda v: setattr(st(), "mouse_delay_play", rt.to_int(v)))
    rw("A_DefaultMouseSpeed", lambda: st().default_mouse_speed, lambda v: setattr(st(), "default_mouse_speed", rt.to_int(v)))
    rw("A_WinDelay", lambda: st().win_delay, lambda v: setattr(st(), "win_delay", rt.to_int(v)))
    rw("A_ControlDelay", lambda: st().control_delay, lambda v: setattr(st(), "control_delay", rt.to_int(v)))
    rw("A_StoreCapsLockMode", lambda: int(st().store_capslock), lambda v: setattr(st(), "store_capslock", to_bool(v)))
    for kind in ("ToolTip", "Pixel", "Mouse", "Caret", "Menu"):
        rw("A_CoordMode" + kind, (lambda k: lambda: st().coord_mode[k])(kind),
           (lambda k: lambda v: _call(rt, "CoordMode", k, v))(kind))
    rw("A_FileEncoding", lambda: st().file_encoding if st().file_encoding != "CP0" else "", lambda v: _call(rt, "FileEncoding", v))
    rw("A_RegView", lambda: st().reg_view, lambda v: setattr(st(), "reg_view", v))
    rw("A_StringCaseSense", lambda: st().string_case_sense, lambda v: setattr(st(), "string_case_sense", rt.to_str(v)))
    rw("A_MaxHotkeysPerInterval", lambda: getattr(rt, "max_hotkeys_per_interval", 70), lambda v: setattr(rt, "max_hotkeys_per_interval", rt.to_int(v)))
    rw("A_HotkeyInterval", lambda: getattr(rt, "hotkey_interval", 2000), lambda v: setattr(rt, "hotkey_interval", rt.to_int(v)))
    rw("A_HotkeyModifierTimeout", lambda: getattr(rt, "hk_mod_timeout", 50), lambda v: setattr(rt, "hk_mod_timeout", rt.to_int(v)))
    rw("A_MenuMaskKey", lambda: getattr(rt, "menu_mask_key", "vkE8"), lambda v: setattr(rt, "menu_mask_key", rt.to_str(v)))
    rw("A_AllowMainWindow", lambda: 0, lambda v: None)
    def _tray_set(attr, value):
        setattr(rt, attr, value)
        from . import tray
        tray.refresh()
    rw("A_IconHidden", lambda: int(getattr(rt, "icon_hidden", False)), lambda v: _tray_set("icon_hidden", to_bool(v)))
    rw("A_IconTip", lambda: getattr(rt, "icon_tip", ""), lambda v: _tray_set("icon_tip", rt.to_str(v)))
    ro("A_IconFile", lambda: "")
    ro("A_IconNumber", lambda: "")
    rw("A_TrayMenu", lambda: _tray(rt), None)
    rw("A_ListLines", lambda: int(getattr(rt.thread.settings, "list_lines", 1)),
       lambda v: setattr(rt.thread.settings, "list_lines", 1 if to_bool(v) else 0))

    # screen / system
    ro("A_ScreenWidth", lambda: window.screen_size()[0])
    ro("A_ScreenHeight", lambda: window.screen_size()[1])
    ro("A_ScreenDPI", lambda: 96)
    ro("A_Cursor", lambda: "Arrow")
    ro("A_CaretX", lambda: "")
    ro("A_CaretY", lambda: "")
    rw("A_Clipboard", lambda: clipboard.get_text(), lambda v: clipboard.set_text(rt.to_str(v)))
    rw("Clipboard", lambda: clipboard.get_text(), lambda v: clipboard.set_text(rt.to_str(v)))


def _call(rt, name, *args):
    return rt.builtins[name.lower()].call(list(args))


def _chdir(rt, v):
    from .files import host_path
    try:
        os.chdir(host_path(rt.to_str(v)))
    except OSError:
        throw("OSError", "The system cannot find the path specified.", rt.to_str(v))


def _loopfield(rt):
    v = rt.thread.loop.field
    return "" if v is UNSET else v


def _loopread(rt):
    v = rt.thread.loop.read_line
    return "" if v is UNSET else v


def _loopfile(rt, attr):
    info = rt.thread.loop.file
    if info is None:
        return ""
    import os.path as P
    from .files import attrib_string
    name = info.name
    if attr in ("Name", "ShortName"):
        return name
    if attr == "Ext":
        i = name.rfind(".")
        return name[i + 1:] if i > 0 else ""
    if attr in ("Path", "ShortPath"):
        return P.join(info.pattern_dir, name) if info.pattern_dir else name
    if attr == "FullPath":
        return info.path
    if attr == "Dir":
        return info.pattern_dir
    st = info.st
    if st is None:
        return ""
    if attr == "Size":
        return st.st_size
    if attr == "SizeKB":
        return st.st_size // 1024
    if attr == "SizeMB":
        return st.st_size // (1024 * 1024)
    if attr == "Attrib":
        return attrib_string(info.path)
    t = {"TimeModified": st.st_mtime, "TimeCreated": getattr(st, "st_birthtime", st.st_ctime),
         "TimeAccessed": st.st_atime}[attr]
    return time.strftime("%Y%m%d%H%M%S", time.localtime(t))


def _loopreg(rt, attr):
    item = rt.thread.loop.reg
    if item is None:
        return ""
    return item.get(attr, "")


def _tray(rt):
    from .gui import tray_menu
    return tray_menu(rt)
