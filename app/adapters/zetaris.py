"""Zetaris adapter: thin re-export of the load-bearing data layer."""

from data_layer.zetaris_client import (
    ZetarisClient,
    ZetarisDataLayerUnavailableError,
)

__all__ = ["ZetarisClient", "ZetarisDataLayerUnavailableError"]
