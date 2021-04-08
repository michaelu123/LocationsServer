import io
import os
import sys
import traceback
from collections import Set, Mapping, deque
from numbers import Number

def printEx(msg, e):
    print(msg, e)
    traceback.print_exc(file=sys.stdout)


def printExToString(msg, e, tracebk=False):
    output = io.StringIO()
    print(msg, ":", e, file=output)
    if tracebk:
        traceback.print_exc(file=output)
    s = output.getvalue()
    output.close()
    return s


def getDataDir():
    if hasattr(sys, "_MEIPASS"):  # i.e. if running as exe produced by pyinstaller
        return sys._MEIPASS
    return "."


def getCurDir():
    if hasattr(sys, "_MEIPASS"):  # i.e. if running as exe produced by pyinstaller
        return sys._MEIPASS
    return "."


def walk(p):
    print("walk", p)
    try:
        if os.path.isdir(p):
            for cp in sorted(os.listdir(p)):
                walk(p + "/" + cp)
    except Exception as e:
        print("walk", p, ":", e)


zero_depth_bases = (str, bytes, Number, range, bytearray)
iteritems = 'items'


def getsize(obj_0):
    """Recursively iterate to sum size of object & members."""
    _seen_ids = set()

    def inner(obj):
        obj_id = id(obj)
        if obj_id in _seen_ids:
            return 0
        _seen_ids.add(obj_id)
        size = sys.getsizeof(obj)
        if isinstance(obj, zero_depth_bases):
            pass  # bypass remaining control flow and return
        elif isinstance(obj, (tuple, list, Set, deque)):
            size += sum(inner(i) for i in obj)
        elif isinstance(obj, Mapping) or hasattr(obj, iteritems):
            size += sum(inner(k) + inner(v) for k, v in getattr(obj, iteritems)())
        # Check for custom object instances - may subclass above too
        if hasattr(obj, '__dict__'):
            size += inner(vars(obj))
        if hasattr(obj, '__slots__'):  # can have __slots__ with __dict__
            size += sum(inner(getattr(obj, s)) for s in obj.__slots__ if hasattr(obj, s))
        return size

    return inner(obj_0)

def normalize(name):
    res = ""
    if name is None:
        return res
    for ch in name:
        if ch.isalnum():
            res += ch
    return res
