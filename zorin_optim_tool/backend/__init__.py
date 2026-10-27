"""Headless backend for Zorin Optimizer.

This package intentionally has no GTK dependency so it can be imported and
tested (and driven by ``zorin-optimizer --doctor``) on a machine without a
desktop session.
"""

__all__ = ["apps", "backup", "dashboard", "performance", "system", "ui_customization", "utils"]
