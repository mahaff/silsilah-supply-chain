"""Reflex configuration for Silsilah.

The website code lives in the app/ folder. app_module_import tells Reflex
to load app/main.py instead of expecting app/app.py.

Regional SQLite files are opened by persistence/. Reflex's own db_url is
left unset on purpose so the UI framework is not the owner of supply-chain data.
"""

import reflex as rx
from reflex.plugins import RadixThemesPlugin, SitemapPlugin

config = rx.Config(
    app_name="app",
    app_module_import="app.main",
    # MVP 1 is a single local page. A generated sitemap is not used.
    disable_plugins=[SitemapPlugin],
    plugins=[
        RadixThemesPlugin(
            theme=rx.theme(
                appearance="light",
                accent_color="teal",
                radius="medium",
            )
        )
    ],
    # Uncommon ports so this app is less likely to collide with another
    # local site on 3000 or an API on 8000.
    frontend_port=3217,
    backend_port=8217,
    backend_host="0.0.0.0",
    api_url="http://127.0.0.1:8217",
)
