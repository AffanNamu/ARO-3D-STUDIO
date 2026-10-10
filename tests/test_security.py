import zipfile

import pytest

from aro_studio.core.errors import InvalidInputError, RateLimitedError, SecurityError
from aro_studio.core.ids import is_valid_id, new_id, require_id
from aro_studio.security.archives import safe_extract_zip
from aro_studio.security.filenames import sanitize_filename, slugify
from aro_studio.security.paths import safe_join
from aro_studio.security.ratelimit import RateLimiter
from aro_studio.security.uploads import require_image_bytes, sniff


@pytest.mark.parametrize("name,expected", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
    ("my truck (final).PNG", "my_truck_final.PNG"),
    ("", "file"),
    ("....", "file"),
    ("con.png", "_con.png"),
    ("a\x00b.jpg", "ab.jpg"),
    ("évil.jpg", "evil.jpg"),
])
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_length_bound():
    assert len(sanitize_filename("a" * 500 + ".png")) <= 80


def test_slugify():
    assert slugify("ARO TITAN 480") == "ARO-TITAN-480"


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "C:\\x", "ok/\x00bad"])
def test_safe_join_blocks_escape(tmp_path, bad):
    with pytest.raises(SecurityError):
        safe_join(tmp_path, bad)


def test_safe_join_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(SecurityError):
        safe_join(root, "link", "file.txt")


def test_safe_join_ok(tmp_path):
    assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()


def test_ids():
    pid = new_id("project")
    assert is_valid_id(pid, "project") and not is_valid_id(pid, "asset")
    with pytest.raises(InvalidInputError):
        require_id("prj_../../x", "project")


def test_sniff_ignores_extension():
    assert sniff(b"\x89PNG\r\n\x1a\n" + b"0" * 20).kind == "png"
    assert sniff(b"MZ\x90\x00").kind == "unknown"
    with pytest.raises(InvalidInputError):
        require_image_bytes(b"<?php system($_GET['x']); ?>", 1_000_000)
    with pytest.raises(InvalidInputError):
        require_image_bytes(b"", 10)
    with pytest.raises(InvalidInputError):
        require_image_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100, 50)


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for n, data in members:
            zf.writestr(n, data)


def test_zip_traversal_rejected(tmp_path):
    z = tmp_path / "a.zip"
    _zip(z, [("../evil.txt", b"x")])
    with pytest.raises(SecurityError):
        safe_extract_zip(z, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_zip_absolute_rejected(tmp_path):
    z = tmp_path / "a.zip"
    _zip(z, [("/abs.txt", b"x")])
    with pytest.raises(SecurityError):
        safe_extract_zip(z, tmp_path / "out")


def test_zip_symlink_rejected(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(SecurityError):
        safe_extract_zip(z, tmp_path / "out")


def test_zip_too_many_members_and_bomb(tmp_path):
    z = tmp_path / "a.zip"
    _zip(z, [(f"f{i}.txt", b"x") for i in range(10)])
    with pytest.raises(SecurityError):
        safe_extract_zip(z, tmp_path / "o1", max_members=5)
    b = tmp_path / "bomb.zip"
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", b"\0" * 5_000_000)
    with pytest.raises(SecurityError):
        safe_extract_zip(b, tmp_path / "o2")  # ratio guard
    with pytest.raises(SecurityError):
        safe_extract_zip(b, tmp_path / "o3", max_uncompressed=1000)


def test_zip_ok(tmp_path):
    z = tmp_path / "a.zip"
    _zip(z, [("dir/a.txt", b"hello")])
    out = safe_extract_zip(z, tmp_path / "out")
    assert out[0].read_bytes() == b"hello"


def test_rate_limiter():
    t = [0.0]
    rl = RateLimiter(3, 60.0, clock=lambda: t[0])
    for _ in range(3):
        rl.check("a")
    with pytest.raises(RateLimitedError):
        rl.check("a")
    rl.check("b")  # independent key
    t[0] = 61.0
    rl.check("a")
