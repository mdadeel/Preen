"""Entry point.

Kept deliberately GTK-free so ``--doctor``, ``--version`` and
``--check-catalog`` work on headless machines and during package builds. The
GUI lives in :mod:`preen_tool.gui` and is imported only when needed.
"""
from __future__ import annotations

import sys

from . import cli
from .backend import utils


def _take_file(argv, flag):
    """Pop ``flag FILE`` off argv; returns FILE or None when malformed."""
    if flag not in argv:
        return ""
    index = argv.index(flag)
    argv.pop(index)
    if index >= len(argv):
        return None
    return argv.pop(index)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--simulate" in argv:
        utils.set_simulate(True)
        argv.remove("--simulate")

    # File-manager handlers act on one file and exit; --appimage-run is
    # GTK-free, the two dialog handlers open a small window at most.
    appimage_run = _take_file(argv, "--appimage-run")
    appimage_handler = _take_file(argv, "--appimage-handler")
    deb_handler = _take_file(argv, "--deb-handler")
    if appimage_run is None or appimage_handler is None or deb_handler is None:
        print("Usage: preen --appimage-handler FILE | --appimage-run FILE "
              "| --deb-handler FILE", file=sys.stderr)
        return 2
    if appimage_run:
        from .backend import appimages as appimages_backend
        outcome = appimages_backend.run_appimage(appimage_run)
        print(outcome.message)
        return 0 if outcome.ok else 1
    if appimage_handler or deb_handler:
        try:
            import gi  # noqa: F401
            gi.require_version("Gtk", "3.0")
        except (ImportError, ValueError) as exc:
            print("Cannot open the handler dialog: {}".format(exc), file=sys.stderr)
            print("Install the GTK bindings first: sudo apt install python3-gi "
                  "gir1.2-gtk-3.0", file=sys.stderr)
            return 1
        from . import handler
        if appimage_handler:
            return handler.run_appimage_handler(appimage_handler)
        return handler.run_deb_handler(deb_handler)

    code = cli.main(argv)
    if code != -1:
        return code

    unknown = [a for a in argv if a.startswith("-")]
    if unknown:
        print("Unknown option(s): {}".format(", ".join(unknown)), file=sys.stderr)
        print("Try: preen --doctor", file=sys.stderr)
        return 2

    try:
        import gi  # noqa: F401
        gi.require_version("Gtk", "3.0")
    except (ImportError, ValueError) as exc:
        print(
            "Cannot start the GUI: {}".format(exc),
            file=sys.stderr,
        )
        print(
            "Install the GTK bindings first:\n"
            "  sudo apt install python3-gi gir1.2-gtk-3.0\n"
            "Then check your installation with: preen --doctor",
            file=sys.stderr,
        )
        return 1

    from .gui import PreenApp

    app = PreenApp()
    return app.run([sys.argv[0]] + argv)


if __name__ == "__main__":
    sys.exit(main())
