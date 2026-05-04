"""
ASGI entrypoint for the code_editor application.

This module exposes an ``application`` callable compatible with ASGI servers.
It intentionally avoids setting a fixed ``DJANGO_SETTINGS_MODULE`` to allow
embedding into any host Django project.  If the environment has not
specified a settings module, you may set ``DJANGO_SETTINGS_MODULE`` before
importing this module.

If the optional Channels dependency is installed and available, this
entrypoint will expose both HTTP and WebSocket protocols via
``ProtocolTypeRouter``.  When Channels is not installed, the fallback
implementation simply returns the standard Django ASGI application.

When WebSockets are enabled, the allowed hosts originate from the
``ALLOWED_HOSTS`` environment variable (comma separated).  The
``AllowedHostsOriginValidator`` wraps the websocket stack to protect
against cross‑origin attacks.  If no websocket routes are defined, the
list remains empty and the validator will effectively disable websocket
connections.
"""

from __future__ import annotations

from typing import List

import os
from django.core.asgi import get_asgi_application

try:
    # Attempt to import Channels components.  If Channels is not
    # installed, an ImportError will be raised and we will fall back to
    # standard Django ASGI application.  These imports must be inside
    # the try block to avoid mandatory dependency on channels.
    from channels.routing import ProtocolTypeRouter, URLRouter  # type: ignore
    from channels.auth import AuthMiddlewareStack  # type: ignore
    from channels.security.websocket import AllowedHostsOriginValidator  # type: ignore
    _channels_available = True
except ImportError:  # pragma: no cover
    ProtocolTypeRouter = None  # type: ignore
    URLRouter = None  # type: ignore
    AuthMiddlewareStack = None  # type: ignore
    AllowedHostsOriginValidator = None  # type: ignore
    _channels_available = False


def _get_django_application():
    """Return the standard Django ASGI application without setting settings module."""
    return get_asgi_application()


def _get_allowed_hosts() -> List[str]:  # pragma: no cover - trivial parsing
    """Parse allowed hosts from the ALLOWED_HOSTS environment variable.

    Returns an empty list when the variable is unset.  Leading/trailing
    whitespace around host names is stripped.  Duplicate entries are
    removed while preserving order.
    """
    hosts_env = os.getenv("ALLOWED_HOSTS", "")
    hosts: List[str] = []
    for host in hosts_env.split(","):
        host = host.strip()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


if _channels_available:
    # Prepare websocket routing.  Importing this list here allows
    # downstream packages to register URL patterns via default import
    # side effects without requiring Channels at import time.  In this
    # repository there are currently no websocket consumers defined.
    websocket_urlpatterns: List = []  # type: ignore[var‑annotated]

    # Build the HTTP application once.  ``get_asgi_application`` may
    # internally load Django settings, so this call occurs only once.
    _django_asgi_app = _get_django_application()

    # Compose the protocol router with websocket support.  The
    # AllowedHostsOriginValidator wraps the AuthMiddlewareStack to ensure
    # websocket connections originate from an allowed host.  The
    # validator does not take a list‑of‑lists; pass the inner application
    # only and rely on ALLOWED_HOSTS from Django settings or environment.
    application = ProtocolTypeRouter({  # type: ignore[call‑arg]
        "http": _django_asgi_app,
        "websocket": AllowedHostsOriginValidator(  # type: ignore[operator]
            AuthMiddlewareStack(  # type: ignore[call‑arg]
                URLRouter(websocket_urlpatterns)  # type: ignore[call‑arg]
            )
        ),
    })
else:
    # Channels is not available; only HTTP requests are supported.
    application = _get_django_application()
