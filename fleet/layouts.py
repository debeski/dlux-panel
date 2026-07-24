"""Fleet overview layout preference: table vs. cards.

Resolution order, mirroring DjangoLux's app-preference convention:
per-user override (``Profile.preferences['app'][FLEET_LAYOUT_NS]``) → global
admin default (``SystemSettings.extra_config['app'][FLEET_LAYOUT_NS]``) → table.
"""

FLEET_LAYOUT_NS = "fleet.overview_layout"
FLEET_LAYOUT_DEFAULT_FIELD = "default_layout"

FLEET_LAYOUT_TABLE = "table"
FLEET_LAYOUT_CARDS = "cards"

FLEET_LAYOUTS = (FLEET_LAYOUT_TABLE, FLEET_LAYOUT_CARDS)
DEFAULT_FLEET_LAYOUT = FLEET_LAYOUT_TABLE


def get_default_fleet_layout():
    """The superuser-set global default, else ``table``."""
    try:
        from dlux.utils import get_app_system_config
        cfg = get_app_system_config(FLEET_LAYOUT_NS, None)
    except Exception:
        return DEFAULT_FLEET_LAYOUT
    value = cfg.get(FLEET_LAYOUT_DEFAULT_FIELD) if isinstance(cfg, dict) else None
    return value if value in FLEET_LAYOUTS else DEFAULT_FLEET_LAYOUT


def get_fleet_layout(request):
    """Effective layout: per-user override → global admin default → table."""
    try:
        prefs = request.user.profile.preferences
    except Exception:
        prefs = None
    app = prefs.get("app") if isinstance(prefs, dict) else None
    user_value = app.get(FLEET_LAYOUT_NS) if isinstance(app, dict) else None
    if user_value in FLEET_LAYOUTS:
        return user_value
    return get_default_fleet_layout()
