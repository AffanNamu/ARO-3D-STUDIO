"""ASGI app for the batch-UI browser test: the real Studio with the plumbing TEST DOUBLE as its only engine.

The UI labels the engine "Plumbing test double (NOT AI)". This exists to exercise queueing, progress, partial failure and
navigation in a browser; it says nothing about model quality or inference.
"""

from aro_studio.api.app import create_app
from aro_studio.app_context import build_context
from aro_studio.config import Settings
from tests.support import PlumbingEngine

ctx = build_context(
    Settings(verified_model_licenses="plumbing_test_double", default_engine="plumbing_test_double"),
    engines=[PlumbingEngine(delay=0.4)],
)
app = create_app(ctx)
