"""Tests here import the real FastAPI app. kiteconnect is a broker SDK that is not needed to test routing,
so a stand-in module is installed before app.main is imported (it is only present in the real runtime)."""

import sys
import types

if "kiteconnect" not in sys.modules:
    stub = types.ModuleType("kiteconnect")
    stub.KiteConnect = type("KiteConnect", (), {"__init__": lambda self, *a, **k: None})
    stub.KiteTicker = type("KiteTicker", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["kiteconnect"] = stub
