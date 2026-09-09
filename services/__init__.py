"""services — business logic.

Every method at a NEW service seam returns Result[T] (core/result); no bare
exception crosses a layer boundary upward. Services never import a bridge.
"""
