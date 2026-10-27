"""Entry point.

Kept deliberately GTK-free so ``--doctor``, ``--version`` and
``--check-catalog`` work on headless machines and during package builds. The
GUI lives in :mod:`zorin_optim_tool.gui` and is imported only when needed.
"""
from __future__ import annotations

import sys

from . import cli
from .backend import utils


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--simulate" in argv:
        utils.set_simulate(True)
        argv.remove("--simulate")

    code = cli.main(argv)
    if code != -1:
        return code

    unknown = [a for a in argv if a.startswith("-")]
    if unknown:
        print("Unknown option(s): {}".format(", ".join(unknown)), file=sys.stderr)
        print("Try: zorin-optimizer --doctor", file=sys.stderr)
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
            "Then check your installation with: zorin-optimizer --doctor",
            file=sys.stderr,
        )
        return 1

    from .gui import ZorinOptimizerApp

    app = ZorinOptimizerApp()
    return app.run([sys.argv[0]] + argv)


if __name__ == "__main__":
    sys.exit(main())
