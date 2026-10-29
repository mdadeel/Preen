"""Headless backend for Preen.

This package intentionally has no GTK dependency so it can be imported and
tested (and driven by ``preen --doctor``) on a machine without a
desktop session.
"""

__all__ = ["appimages", "apps", "backup", "dashboard", "deepclean", "firewall",
           "kernels", "performance", "settings", "services", "system",
           "ui_customization", "utils"]
