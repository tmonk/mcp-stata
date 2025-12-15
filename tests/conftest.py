import os

# Work around Windows PermissionError when pytest tries to unlink the
# pytest-current symlink during temp directory cleanup. Pytest's cleanup
# lives in _pytest.pathlib.cleanup_dead_symlinks; wrap it to ignore
# PermissionError so test runs don't warn/fail on exit.
if os.name == "nt":
    try:
        import _pytest.pathlib as _pl  # type: ignore
    except Exception:
        _pl = None

    if _pl is not None:
        _orig_cleanup_dead_symlinks = getattr(_pl, "cleanup_dead_symlinks", None)

        def _cleanup_dead_symlinks_safe(root):
            if _orig_cleanup_dead_symlinks is None:
                return
            try:
                _orig_cleanup_dead_symlinks(root)
            except PermissionError:
                # Ignore symlink removal failures (e.g., antivirus or handle held)
                return

        _pl.cleanup_dead_symlinks = _cleanup_dead_symlinks_safe  # type: ignore
