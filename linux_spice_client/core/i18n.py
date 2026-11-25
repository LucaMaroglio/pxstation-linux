"""Interface language (same rules as PxStation Mac).

Texts in the code are English and go through ``_()``; translations live in
``data/locale/<code>.json`` ({"strings": {english: translation}}). The language is:

1. the one chosen in Preferences › General (``language`` in settings.json), or
2. the first supported language in the system preferences (``LANGUAGE``, ``LC_ALL``,
   ``LC_MESSAGES``, ``LANG``), or
3. English, when none of those is supported.

``setup()`` must run before the interface modules are imported (some texts are module
constants). A change applies after a restart, as on macOS.
"""

from __future__ import annotations

import json
import logging
import os

from .. import APP_SLUG, DATA_DIR

log = logging.getLogger(__name__)

SOURCE_LANGUAGE = "en"
LOCALE_DIR = os.path.join(DATA_DIR, "locale")

# Language names in their own language, for the preferences.
_NAMES = {"en": "English", "it": "Italiano", "de": "Deutsch", "fr": "Français", "es": "Español",
          "pt": "Português", "nl": "Nederlands", "pl": "Polski"}

_catalog: dict[str, str] = {}
_current = SOURCE_LANGUAGE
_chosen_at_start = ""


def _(text: str) -> str:
    """The text in the interface language (the English text itself when untranslated)."""
    return _catalog.get(text, text)


def supported_languages() -> list[str]:
    """English plus one entry per catalog in data/locale, English first."""
    codes = set()
    try:
        codes = {name[:-5] for name in os.listdir(LOCALE_DIR) if name.endswith(".json")}
    except OSError:
        pass
    codes.discard(SOURCE_LANGUAGE)
    return [SOURCE_LANGUAGE] + sorted(codes, key=language_name)


def language_name(code: str) -> str:
    return _NAMES.get(code, code)


def _normalize(value: str) -> str:
    """``it_IT.UTF-8`` / ``it-IT`` / ``it`` → ``it``; ``C`` and ``POSIX`` → ``""``."""
    value = value.split(".")[0].split("@")[0].replace("-", "_")
    code = value.split("_")[0].lower()
    return "" if code in ("c", "posix") else code


def system_preferences(environ=os.environ) -> list[str]:
    """Language codes the system asks for, in order (gettext rules: LANGUAGE is a list and
    is honoured unless the locale is C; then LC_ALL, LC_MESSAGES, LANG)."""
    locale_value = environ.get("LC_ALL") or environ.get("LC_MESSAGES") or environ.get("LANG") or ""
    codes = []
    if environ.get("LANGUAGE") and _normalize(locale_value):
        codes += [_normalize(part) for part in environ["LANGUAGE"].split(":")]
    codes.append(_normalize(locale_value))
    return [code for code in dict.fromkeys(codes) if code]


def system_language(environ=os.environ) -> str:
    """The supported language the system preferences resolve to (English if none)."""
    supported = supported_languages()
    return next((code for code in system_preferences(environ) if code in supported), SOURCE_LANGUAGE)


def _config_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_SLUG, "settings.json")


def chosen_language() -> str:
    """The language saved in the preferences ("" = system default)."""
    try:
        with open(_config_file(), encoding="utf-8") as handle:
            value = json.load(handle).get("language", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) and value in supported_languages() else ""


def chosen_at_start() -> str:
    """The choice this process runs with ("" = system default)."""
    return _chosen_at_start


def current_language() -> str:
    return _current


def load(code: str) -> None:
    global _catalog, _current
    _catalog, _current = {}, SOURCE_LANGUAGE
    if code == SOURCE_LANGUAGE:
        return
    try:
        with open(os.path.join(LOCALE_DIR, f"{code}.json"), encoding="utf-8") as handle:
            _catalog = dict(json.load(handle)["strings"])
        _current = code
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("Cannot load the %s translation: %s", code, error)


def setup() -> str:
    """Loads the interface language and makes GTK, Qt and remote-viewer (gettext) follow it.
    Returns the language code in use."""
    global _chosen_at_start
    _chosen_at_start = chosen_language()
    code = _chosen_at_start or system_language()
    load(code)
    if _chosen_at_start:
        # Toolkit texts (GTK dialogs, remote-viewer) follow LANGUAGE when the locale isn't C.
        os.environ["LANGUAGE"] = _current
    return _current
