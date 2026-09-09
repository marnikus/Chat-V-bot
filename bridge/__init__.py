"""bridge — one router + nine domain bridges.

The Router (bridge/router.py) is the single QObject registered on the
QWebChannel; it publishes every domain bridge's slots and re-emits every
domain signal, so the JS wire API is unchanged while the implementation
is split by domain. Each domain bridge owns @Slot methods for ONE domain
and depends on services through the shared BridgeContext.
"""
