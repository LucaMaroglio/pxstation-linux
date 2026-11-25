"""Entry point: picks the GTK or the Qt interface for the current desktop."""

from __future__ import annotations

import logging
import os
import sys

from . import APP_SLUG


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    logging.basicConfig(level=logging.DEBUG if os.environ.get("LSC_DEBUG") else logging.WARNING,
                        format="%(name)s: %(message)s")
    log = logging.getLogger("linux_spice_client")

    # Interface language first: some texts are module constants of the modules below.
    from .core import i18n
    log.info("language: %s", i18n.setup())

    from .core import remote
    argv, action = remote.take_action_argument(argv)
    if action and remote.activate_action(action):
        return 0  # the running instance does it
    if action == "quit":
        return 0  # nothing running, nothing to quit

    from .core.environment import QT, choose_interface
    interface, warning = choose_interface()
    if warning:
        log.warning(warning)
    log.info("interface: %s", interface)

    from gi.repository import GLib
    GLib.set_prgname(APP_SLUG)
    if interface == QT:
        from .qt.app import run
    else:
        from .gtk.app import run
    return run(argv, action)


if __name__ == "__main__":
    sys.exit(main())
