"""File bridge orchestration — facade (H-C5 split)

Now ≤30 LOC via merge/apply/io split.
"""

from __future__ import annotations

from bridge.file_bridge_apply import apply_block, apply_stack, save_imported_preset
from bridge.file_bridge_io import export_file, import_file_result, revalidate
from bridge.file_bridge_merge import merge_library

__all__ = ["merge_library", "apply_stack", "apply_block", "save_imported_preset", "export_file", "import_file_result", "revalidate"]
