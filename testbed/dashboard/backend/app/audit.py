"""Operator audit trail. Every control action is written as one JSON line to stdout,
so Alloy ships it to Loki like any other log (namespace sixg-control, container dashboard)."""
import json
import time


def _running_test():
    from . import testrecords  # local import: testrecords is optional at import time
    try:
        return next((t["id"] for t in testrecords.all_tests() if t["state"] == "running"), None)
    except Exception:
        return None


def record(action, target=None, result="ok", session=None, **detail):
    session = session or _running_test()
    entry = {"audit": True, "ts": time.time(), "action": action, "target": target,
             "result": result, "session": session, **detail}
    print(json.dumps(entry), flush=True)
    return entry
