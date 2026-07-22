"""Spell-check backend: the Windows Spell Checking API, bound with ctypes.

Deliberately Qt-free -- like :mod:`pcc.model` -- so it can be exercised without a
widget in sight, and so the UI layer above it can be tested against a fake.

Why a hand-written COM binding rather than a package:

* ``pywin32`` cannot reach it. ``ISpellChecker`` is a raw COM interface with no
  ``IDispatch``, so ``win32com.client.Dispatch`` has nothing to bind to.
* ``comtypes`` would do it, but this project keeps ``requirements.txt`` short on
  purpose, and the binding below is forty lines of vtable calls.
* A bundled dictionary would be a megabyte to ship and would drift out of date.
  The system checker already knows the user's own added words, and :func:`add`
  writes back to that same dictionary -- so a word taught to PCC is a word Word
  and Edge already know.

Everything degrades to "no spell check" rather than to an exception:
:func:`available` latches to ``False`` the first time anything fails, and
:func:`is_correct` answers ``True`` -- never underline what we cannot judge.

Measured on the reference machine: the one-time factory + checker construction
costs ~70 ms (paid during the palette's prewarm, off the trigger path), a single
word check 0.25 ms, and a ``Suggest`` call 4 ms.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_int, c_ulong, c_void_p, c_wchar_p

#: Words remembered per process. A miss costs 0.25 ms, a hit costs a dict
#: lookup, and prose repeats itself -- so this is what makes typing free.
#: Cleared wholesale rather than evicted one at a time: the ceiling exists to
#: bound memory, not to be lived at.
MAX_CACHE = 50_000

#: Suggestions are for picking from at a glance, not for browsing.
MAX_SUGGESTIONS = 6

_CLSID_SPELL_CHECKER_FACTORY = "{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}"
_IID_SPELL_CHECKER_FACTORY = "{8E018A9D-2415-4677-BF08-794EA61F94BB}"

_CLSCTX_INPROC_SERVER = 1
_COINIT_APARTMENTTHREADED = 2

# Vtable slots, counted from IUnknown's three. These were verified by calling
# them, not by reading a header.
_RELEASE = 2
_FACTORY_SUPPORTED_LANGUAGES = 3
_FACTORY_IS_SUPPORTED = 4
_FACTORY_CREATE = 5
_CHECKER_CHECK = 4
_CHECKER_SUGGEST = 5
_CHECKER_ADD = 6
_CHECKER_IGNORE = 7
_ENUM_NEXT = 3

_factory: c_void_p | None = None
_checker: c_void_p | None = None
_language: str | None = None
_requested_language: str | None = None
_languages: list[str] | None = None
_broken = False
_cache: dict[str, bool] = {}


# --- COM plumbing -----------------------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


def _ole32():
    # Resolved on demand: importing this module must not fail off Windows, which
    # is what lets the tests import it anywhere.
    return ctypes.oledll.ole32


def _guid(text: str) -> _GUID:
    result = _GUID()
    _ole32().CLSIDFromString(text, byref(result))
    return result


def _method(pointer, index: int, *argtypes):
    """Bind vtable slot ``index`` of the interface at ``pointer``.

    ``ctypes.HRESULT`` as the return type means a failed call raises ``OSError``
    on its own, so no call site has to check a status code by hand.
    """
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(pointer) -> None:
    if pointer:
        try:
            _method(pointer, _RELEASE)(pointer)
        except OSError:
            pass


def _take_string(pointer: c_void_p) -> str:
    """Read a ``LPOLESTR`` out param and free it, as COM requires of the caller."""
    if not pointer:
        return ""
    try:
        return ctypes.wstring_at(pointer)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def _drain_strings(enumerator: c_void_p, limit: int) -> list[str]:
    """Pull up to ``limit`` items out of an ``IEnumString``."""
    items: list[str] = []
    next_item = _method(enumerator, _ENUM_NEXT, c_ulong, POINTER(c_void_p), POINTER(c_ulong))
    while len(items) < limit:
        value = c_void_p()
        fetched = c_ulong(0)
        if next_item(enumerator, 1, byref(value), byref(fetched)) != 0 or not fetched.value:
            break
        items.append(_take_string(value))
    return items


# --- lifecycle --------------------------------------------------------------


def _default_language() -> str:
    """The user's own UI language when the checker supports it, else en-US."""
    buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
    try:
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
            return buffer.value
    except OSError:
        pass
    return "en-US"


def _pick_language(factory) -> str:
    """Resolve the tag to build the checker with.

    An explicit setting wins; otherwise the user's locale, then en-US, then
    whatever the machine actually has installed. Falling back rather than
    failing means a Hebrew or Japanese Windows still gets English marks instead
    of no marks at all.
    """
    is_supported = _method(factory, _FACTORY_IS_SUPPORTED, c_wchar_p, POINTER(c_int))

    def supported(tag: str) -> bool:
        value = c_int(0)
        try:
            is_supported(factory, tag, byref(value))
        except OSError:
            return False
        return bool(value.value)

    for tag in (_requested_language, _default_language(), "en-US"):
        if tag and supported(tag):
            return tag
    return (_installed_languages(factory) or ["en-US"])[0]


def _installed_languages(factory) -> list[str]:
    global _languages
    if _languages is None:
        enumerator = c_void_p()
        try:
            _method(factory, _FACTORY_SUPPORTED_LANGUAGES, POINTER(c_void_p))(
                factory, byref(enumerator)
            )
            _languages = _drain_strings(enumerator, 200)
        except OSError:
            _languages = []
        finally:
            _release(enumerator)
    return _languages


def _ensure() -> bool:
    """Build the checker once. ``False`` means this machine has none."""
    global _factory, _checker, _broken, _language
    if _broken:
        return False
    if _checker is not None:
        return True
    try:
        # Qt already OleInitializes the GUI thread; this is the harmless
        # belt-and-braces for anyone calling us from a bare interpreter.
        # S_FALSE and RPC_E_CHANGED_MODE are both fine, hence windll not oledll.
        ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)

        factory = c_void_p()
        _ole32().CoCreateInstance(
            byref(_guid(_CLSID_SPELL_CHECKER_FACTORY)),
            None,
            _CLSCTX_INPROC_SERVER,
            byref(_guid(_IID_SPELL_CHECKER_FACTORY)),
            byref(factory),
        )
        language = _pick_language(factory)

        checker = c_void_p()
        _method(factory, _FACTORY_CREATE, c_wchar_p, POINTER(c_void_p))(
            factory, language, byref(checker)
        )
    except (OSError, AttributeError, ValueError):
        # AttributeError covers a non-Windows interpreter, where ctypes has no
        # oledll at all -- the tests import this module on any platform.
        _broken = True
        return False

    _factory, _checker, _language = factory, checker, language
    return True


def warm() -> None:
    """Pay the ~70 ms construction cost now, wherever "now" is convenient."""
    _ensure()


def available() -> bool:
    return _ensure()


def language() -> str | None:
    """The tag the live checker was built with, or ``None`` if there is none."""
    return _language if _ensure() else None


def languages() -> list[str]:
    """Language tags this machine can check, best-first. Empty when unavailable."""
    if not _ensure():
        return []
    return list(_installed_languages(_factory))


def set_language(tag: str | None) -> None:
    """Rebuild against ``tag`` (``None`` restores the automatic choice)."""
    global _checker, _requested_language, _broken
    if tag == _requested_language and _checker is not None:
        return
    _requested_language = tag or None
    _release(_checker)
    _checker = None
    # A bad tag in a hand-edited settings.json must cost the custom language,
    # not the feature.
    _broken = False
    _cache.clear()


def reset() -> None:
    """Drop every COM object and cached answer. Used by the tests."""
    global _factory, _checker, _languages, _language, _broken
    _release(_checker)
    _release(_factory)
    _factory = _checker = None
    _languages = None
    _language = None
    _broken = False
    _cache.clear()


# --- checking ---------------------------------------------------------------


def _has_error(text: str) -> bool:
    """Whether the checker reports any spelling error inside ``text``."""
    errors = c_void_p()
    _method(_checker, _CHECKER_CHECK, c_wchar_p, POINTER(c_void_p))(
        _checker, text, byref(errors)
    )
    if not errors:
        return False
    try:
        item = c_void_p()
        _method(errors, _ENUM_NEXT, POINTER(c_void_p))(errors, byref(item))
        if not item:
            return False
        _release(item)
        return True
    finally:
        _release(errors)


def is_correct(word: str) -> bool:
    """Whether ``word`` is spelled correctly.

    Answers ``True`` for anything it cannot judge: a missing checker must show
    up as an absence of marks, never as a page full of false ones.
    """
    cached = _cache.get(word)
    if cached is not None:
        return cached
    if not _ensure():
        return True
    try:
        correct = not _has_error(word)
    except OSError:
        return True
    if len(_cache) >= MAX_CACHE:
        _cache.clear()
    _cache[word] = correct
    return correct


def suggest(word: str) -> list[str]:
    """Replacements for ``word``, best-first. Only ever called for one word."""
    if not _ensure():
        return []
    enumerator = c_void_p()
    try:
        _method(_checker, _CHECKER_SUGGEST, c_wchar_p, POINTER(c_void_p))(
            _checker, word, byref(enumerator)
        )
        return [item for item in _drain_strings(enumerator, MAX_SUGGESTIONS) if item]
    except OSError:
        return []
    finally:
        _release(enumerator)


def _teach(slot: int, word: str) -> bool:
    if not word or not _ensure():
        return False
    try:
        _method(_checker, slot, c_wchar_p)(_checker, word)
    except OSError:
        return False
    _cache[word] = True
    return True


def add(word: str) -> bool:
    """Add to the user's Windows dictionary. Persistent, and shared system-wide."""
    return _teach(_CHECKER_ADD, word)


def ignore(word: str) -> bool:
    """Accept ``word`` for the life of this process only."""
    return _teach(_CHECKER_IGNORE, word)
