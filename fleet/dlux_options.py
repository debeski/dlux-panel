"""DjangoLux Options-page registrations for the fleet overview layout.

Auto-imported at startup by dlux's option autodiscovery (``<app>.dlux_options``).

  * A per-user picker card (``register_card``) — each operator chooses table or
    cards for their own fleet view, persisted to their profile preferences.
  * A superuser settings tile (``register_app_settings``) that sets the fleet-wide
    default, saved to ``SystemSettings.extra_config['app'][FLEET_LAYOUT_NS]``. The
    per-user pick overrides it.
"""
from dlux.options import register_card
from dlux.translations import get_strings

from .layouts import (
    FLEET_LAYOUT_DEFAULT_FIELD,
    FLEET_LAYOUT_NS,
    get_fleet_layout,
)

try:
    from dlux.options import register_app_settings
except ImportError:  # pragma: no cover - depends on runtime dlux version
    register_app_settings = None

try:
    from dlux.widgets import DluxChoiceSelectorWidget
except ImportError:  # pragma: no cover - depends on runtime dlux version
    DluxChoiceSelectorWidget = None


LAYOUT_ICONS = {"table": "bi-table", "cards": "bi-grid-3x3-gap-fill"}


def _layout_choices():
    s = get_strings()
    return [
        ("table", s.get("fleet_layout_table", "Table")),
        ("cards", s.get("fleet_layout_cards", "Cards")),
    ]


def _layout_option_meta():
    return {value: {"icon": icon} for value, icon in LAYOUT_ICONS.items()}


def _card_title(request):
    return get_strings().get("fleet_layout_title", "Fleet layout")


def _card_context(request):
    current = get_fleet_layout(request)
    selector_html = None
    if DluxChoiceSelectorWidget is not None:
        widget = DluxChoiceSelectorWidget(variant="toggle", option_meta=_layout_option_meta())
        widget.choices = _layout_choices()
        selector_html = widget.render(
            "fleet_overview_layout", current, attrs={"id": "id_fleet_overview_layout"}
        )
    return {
        "fleet_layout": current,
        "fleet_layout_ns": FLEET_LAYOUT_NS,
        "fleet_layout_selector_html": selector_html,
    }


register_card(
    id="fleet.overview_layout",
    title=_card_title,
    template_name="fleet/options/layout_card.html",
    icon="bi-grid-3x3-gap",
    order=50,
    permission="fleet.view_managedproject",
    context_builder=_card_context,
)


if register_app_settings is not None:
    register_app_settings(
        namespace=FLEET_LAYOUT_NS,
        title=lambda request: get_strings().get("fleet_layout_default_title", "Default fleet layout"),
        description=lambda request: get_strings().get(
            "fleet_layout_default_desc",
            "The fleet-wide default overview. Each operator can still override it.",
        ),
        icon="bi-grid-3x3-gap",
        order=50,
        fields=[
            {
                "name": FLEET_LAYOUT_DEFAULT_FIELD,
                "type": "choice",
                "control": "selector",
                "variant": "toggle",
                "css_class": "col-12",
                "label": lambda request: get_strings().get("fleet_layout_default_title", "Default fleet layout"),
                "choices": _layout_choices(),
                "option_meta": _layout_option_meta(),
                "default": "table",
            },
        ],
        defaults={FLEET_LAYOUT_DEFAULT_FIELD: "table"},
    )
