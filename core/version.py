"""App version — stamped into every exported preset file.

Lives in ``core`` (not ``app``) because ``services/`` may import
``core`` but never ``app`` (``app/__init__.py`` pulls the window stack
and would create a cycle). ``1.0.0`` is the first versioned export;
bump it whenever an export-format or behaviour change could affect
files made by other installs (see
``docs/STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md`` §3.3).
"""

APP_VERSION = "1.0.0"

__all__ = ["APP_VERSION"]
