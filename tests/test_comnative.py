"""The foreign-IDispatch client path of comnative: a DispatchObject over a plain Python target (not one of the
script's objects), reached only through its interface pointer with ComDispatch(ForeignImpl(ptr)), so every member
access goes through GetIDsOfNames/Invoke and VARIANTs.

Run: python3 tests/test_comnative.py
"""
import gc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bunnyhotkey.loader import Program  # noqa: E402

failures = 0


def check(name, got, want):
    global failures
    if got == want and type(got) is type(want):
        print(f"PASS {name}")
    else:
        failures += 1
        print(f"FAIL {name}: got {got!r} want {want!r}")


prog = Program("*", [], {"backend": "null", "gui_errors": False})
rt = prog.rt
from bunnyhotkey.lib import comnative as N  # noqa: E402
from bunnyhotkey.lib.com import ComDispatch  # noqa: E402
from bunnyhotkey.objects import AhkArray  # noqa: E402
from bunnyhotkey.errors import AhkThrow  # noqa: E402


class Child:
    def get(self, name, args):
        if name and name.lower() == "label":
            return "inner"
        raise N.ComFailure(N.DISP_E_MEMBERNOTFOUND)

    def set(self, name, args, value):
        raise N.ComFailure(N.DISP_E_MEMBERNOTFOUND)

    def call(self, name, args):
        return self.get(name, args)


class Target:
    """Members: properties n, f, s, b, kid (a nested IDispatch); methods Echo, Add; [i] items; _NewEnum."""

    def __init__(self):
        self.props = {"n": 5, "f": 2.5, "s": "bunny", "b": True}
        self.items = ["zero", "one"]
        self.kid = N.DispatchObject(Child())
        self.kid.refs = 1                       # held by this target

    def get(self, name, args):
        if name is None:
            return self.items[args[0]]
        key = name.lower()
        if key == "kid":
            return ComDispatch(N.ForeignImpl(N.addref(self.kid.ptr) and self.kid.ptr))
        if key in self.props:
            return self.props[key]
        raise N.ComFailure(N.DISP_E_MEMBERNOTFOUND)

    def set(self, name, args, value):
        if name is None:
            self.items[args[0]] = value
        else:
            self.props[name.lower()] = value

    def call(self, name, args):
        key = (name or "").lower()
        if key == "echo":
            return args[0]
        if key == "add":
            return sum(args)
        return self.get(name, args)             # DISPATCH_METHOD|PROPERTYGET on a property

    def enum_object(self):
        arr = AhkArray(None, ["x", 7, 1.5])
        return N.EnumVariant(rt.call_method(arr, "__Enum", [1]))


target = Target()
server = N.DispatchObject(target)               # refs 1: ours
ptr = server.ptr
check("not ours", N.lookup(ptr) is server and not hasattr(server, "_obj"), True)

N.addref(ptr)                                   # the wrapper takes this reference
obj = ComDispatch(N.ForeignImpl(ptr))
check("refs after wrap", server.refs, 2)
impl = obj.impl

# ---- VARIANT round trips through Invoke
check("get int", impl.get("n", []), 5)
check("get float", impl.get("f", []), 2.5)
check("get str", impl.get("s", []), "bunny")
check("get bool", impl.get("b", []), 1)                        # VT_BOOL reads back as 1, like AutoHotkey
check("echo int", impl.call("Echo", [42]), 42)
check("echo big int", impl.call("Echo", [1 << 40]), 1 << 40)   # VT_I8
check("echo negative", impl.call("Echo", [-7]), -7)
check("echo float", impl.call("Echo", [-0.125]), -0.125)
check("echo str", impl.call("Echo", ["héllo ✓"]), "héllo ✓")
check("echo empty str", impl.call("Echo", [""]), "")
check("echo bool", impl.call("Echo", [True]), 1)
check("add", impl.call("Add", [1, 2, 3.5]), 6.5)
check("argument order", impl.call("Echo", ["first", "second"]), "first")

# ---- property put (DISPID_PROPERTYPUT named argument) and the default member
impl.set("n", [], 99)
check("set int", target.props["n"], 99)
impl.set("s", [], "carrot")
check("set str", impl.get("s", []), "carrot")
check("default get", impl.get(impl.default, [1]), "one")
impl.set(impl.default, [0], "ZERO")
check("default set", target.items[0], "ZERO")

# ---- a nested IDispatch comes back as another foreign ComObject
kid = impl.get("kid", [])
check("nested type", type(kid).__name__ + "/" + type(kid.impl).__name__, "ComDispatch/ForeignImpl")
check("nested get", kid.impl.get("label", []), "inner")
gc.collect()                                    # ComDispatch <-> impl.owner is a cycle: Release waits for gc
check("nested refs", target.kid.refs, 2)
del kid
gc.collect()
check("nested released", target.kid.refs, 1)

# ---- an object passed in comes back as the same interface (a new wrapper, as ComObjFromPtr gives on Windows)
echo_obj = impl.call("Echo", [obj])
check("object round trip", N.object_ptr(echo_obj), ptr)

# ---- _NewEnum -> IEnumVARIANT
check("enum", list(impl.enum()), ["x", 7, 1.5])

# ---- errors become OSError with the HRESULT
try:
    impl.get("nope", [])
    check("missing member", "no error", "OSError")
except AhkThrow as e:
    msg = rt.to_str(rt.get_prop(e.value, "Message"))
    check("missing member", (rt.to_str(rt.get_prop(e.value, "__Class")), msg[:12]), ("OSError", "(0x80020003)"))

# ---- the wrapper's reference goes away with it
gc.collect()
check("refs before drop", server.refs, 3)          # obj and echo_obj
del obj, impl, echo_obj
gc.collect()
check("refs after drop", server.refs, 1)

print("ok" if not failures else f"{failures} failed")
sys.exit(1 if failures else 0)
