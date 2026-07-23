from typing import Any

def classFactory(iface: Any) -> Any:
    from .main import PowerCorridorPlugin
    return PowerCorridorPlugin(iface)