"""Thin re-exports: the compliance layer points at the real clients.

Nothing is reimplemented here. Zetaris and Meterless integrations live
in data_layer and cognition; these adapters exist so the official
repo layout (app/adapters/) resolves to the load-bearing code.
"""

from app.adapters.meterless import (
    create_injected_generator,
    discover_models,
)
from app.adapters.zetaris import (
    ZetarisClient,
    ZetarisDataLayerUnavailableError,
)

__all__ = [
    "create_injected_generator",
    "discover_models",
    "ZetarisClient",
    "ZetarisDataLayerUnavailableError",
]
