"""ASGI app for the engine-picker browser test: the real Studio with THREE labelled test doubles (never AI).

``plumbing_test_double`` and ``second_test_double`` can run; ``third_test_double`` reports itself unavailable so the UI's
"cannot run here" path is exercised. Nothing here says anything about model quality.
"""

from aro_studio.api.app import create_app
from aro_studio.app_context import build_context
from aro_studio.config import Settings
from tests.support import PlumbingEngine


def _double(eid: str, name: str, available: bool) -> PlumbingEngine:
    e = PlumbingEngine(available=available)
    e.info = e.info.__class__(**{**PlumbingEngine.info.__dict__, "id": eid, "name": name})
    return e


ctx = build_context(
    Settings(
        verified_model_licenses="plumbing_test_double,second_test_double,third_test_double",
        default_engine="plumbing_test_double",
    ),
    engines=[
        _double("plumbing_test_double", "Plumbing test double (NOT AI)", True),
        _double("second_test_double", "Second test double (NOT AI)", True),
        _double("third_test_double", "Third test double (NOT AI)", False),
    ],
)
app = create_app(ctx)
