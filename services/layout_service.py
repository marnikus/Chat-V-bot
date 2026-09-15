"""LayoutService — facade (H-C5 split)

Now ≤30 LOC via tree/payload split.
"""

from __future__ import annotations

from services.layout_service_payload import LayoutServicePayload


class LayoutService(LayoutServicePayload):
    pass


__all__ = ["LayoutService"]
