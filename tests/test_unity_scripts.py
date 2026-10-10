"""The C# files shipped in the Unity package must at least PARSE (tree-sitter).

This is a syntax check only. It does NOT prove the scripts compile against the Unity API or behave correctly: that needs a
Unity 6 editor (docs/verification/unity-verification-runbook.md). Without tree-sitter-c-sharp the test is SKIPPED, not passed.
"""

from __future__ import annotations

import pytest

from aro_studio.export.unity_templates import DESCRIPTOR_CS, IMPORTER_CS
from aro_studio.export.unity_verifier import VERIFIER_CS

ts = pytest.importorskip("tree_sitter")
cs = pytest.importorskip("tree_sitter_c_sharp")


def _errors(node, out):
    if node.type == "ERROR" or node.is_missing:
        out.append((node.start_point, node.type))
    for c in node.children:
        _errors(c, out)
    return out


@pytest.mark.parametrize(
    "name,src",
    [("AroAssetImporter", IMPORTER_CS), ("AroVehicleDescriptor", DESCRIPTOR_CS), ("AroUnityVerifier", VERIFIER_CS)],
)
def test_csharp_parses_without_errors(name, src):
    parser = ts.Parser(ts.Language(cs.language()))
    tree = parser.parse(src.encode())
    errs = _errors(tree.root_node, [])
    assert not errs, f"{name}: syntax errors at {errs[:5]}"


def test_the_syntax_check_can_actually_fail():
    parser = ts.Parser(ts.Language(cs.language()))
    tree = parser.parse(b"class A { void M( { int x = ; } ")
    assert _errors(tree.root_node, [])
