"""Shared test setup.

Tests that import the real FastAPI app need `kiteconnect`, the Zerodha SDK, which is only present in the
real runtime. When it is not installed a stand-in module is registered; routing and auth do not use it.
"""

import sys
import types

try:
    import kiteconnect  # noqa: F401
except ImportError:
    stub = types.ModuleType("kiteconnect")
    stub.KiteConnect = type("KiteConnect", (), {"__init__": lambda self, *a, **k: None})
    stub.KiteTicker = type("KiteTicker", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["kiteconnect"] = stub
