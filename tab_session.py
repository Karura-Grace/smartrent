# tab_session.py
# Provides per-tab session isolation within the same browser.
#
# How it works:
#   - Each browser tab generates a unique `tab_id` stored in sessionStorage
#     (sessionStorage is isolated per-tab by the browser).
#   - Every page load injects the tab_id into a <meta> tag.
#   - A small JS snippet reads it and appends ?tab_id=... to every form/link,
#     and sends it as X-Tab-Id header on fetch requests.
#   - The server stores all tab sessions inside the main flask session as:
#       session['tabs'] = { tab_id: { user_id, role, user_name, ... }, ... }
#   - tab_session() returns the dict for the current tab_id.

import uuid
from flask import session, request


TAB_SESSIONS_KEY = 'tabs'
MAX_TABS = 20  # prevent unbounded growth


def _get_tab_id():
    """Read tab_id from request: query param, form field, or header."""
    return (
        request.args.get('tab_id')
        or request.form.get('tab_id')
        or request.headers.get('X-Tab-Id')
        or ''
    ).strip()


def get_tab_id():
    """Return the current tab_id, or empty string if not present."""
    return _get_tab_id()


def tab_session():
    """
    Return the mutable session dict for the current tab.
    Creates an empty entry if the tab_id is new.
    """
    tab_id = _get_tab_id()
    if not tab_id:
        # Fallback: return the root session so nothing breaks
        return session

    if TAB_SESSIONS_KEY not in session:
        session[TAB_SESSIONS_KEY] = {}

    tabs = session[TAB_SESSIONS_KEY]

    if tab_id not in tabs:
        # Evict oldest tabs if we hit the limit
        if len(tabs) >= MAX_TABS:
            oldest = next(iter(tabs))
            del tabs[oldest]
        tabs[tab_id] = {}

    # flask-session needs us to mark the session modified when mutating nested dicts
    session.modified = True
    return tabs[tab_id]


def clear_tab_session():
    """Clear only the current tab's session data (logout for this tab)."""
    tab_id = _get_tab_id()
    if tab_id and TAB_SESSIONS_KEY in session:
        session[TAB_SESSIONS_KEY].pop(tab_id, None)
        session.modified = True
