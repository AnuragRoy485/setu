import random
import string

import pytest

from setu import qr


def test_sizes_and_symmetry():
    m = qr.make("hello", "L")
    assert len(m) == 21 and all(len(r) == 21 for r in m)
    # finder pattern corners
    assert m[0][0] and m[0][6] and m[6][0] and m[3][3] and not m[1][1]


def test_version_grows_with_data():
    assert len(qr.make("x" * 100, "L")) < len(qr.make("x" * 300, "L"))
    assert len(qr.make("x" * 100, "M")) > len(qr.make("x" * 100, "L"))


def test_too_long():
    with pytest.raises(ValueError):
        qr.make("x" * 5000)


def test_renderers():
    m = qr.make("setu", "L")
    assert qr.to_svg(m).startswith("<svg")
    assert qr.to_png(m)[:8] == b"\x89PNG\r\n\x1a\n"
    assert "█" in qr.to_terminal(m) or "▀" in qr.to_terminal(m)


def _image(m, scale=6, border=4):
    np = pytest.importorskip("numpy")
    n = len(m)
    img = np.full(((n + 2 * border) * scale,) * 2, 255, np.uint8)
    for y in range(n):
        for x in range(n):
            if m[y][x]:
                img[(y + border) * scale:(y + border + 1) * scale, (x + border) * scale:(x + border + 1) * scale] = 0
    return img


def _decode(m):
    zx = pytest.importorskip("zxingcpp")  # pip install zxing-cpp
    got = zx.read_barcodes(_image(m))
    return got[0].text if got else None


@pytest.mark.parametrize("ec", ["L", "M"])
def test_decodes_real_configs(ec):
    """Real client configs of many random keys decode back exactly.

    Uses zxing-cpp. OpenCV's QRCodeDetector fails on roughly 1 in 7 large, perfectly valid
    codes (versions 14+), which made the old test flaky; zxing decodes all of them."""
    from setu import config, state as S
    for _ in range(25):
        s = S.new_state("203.0.113.7")
        d = S.add_device(s, "alice-phone")
        text = config.render_client_conf(s, d)
        assert _decode(qr.make(text, ec)) == text


def test_decodes_many_lengths():
    rng = random.Random(7)
    alphabet = string.ascii_letters + string.digits + "+/=: \n"
    for length in list(range(1, 200, 5)) + list(range(200, 1000, 50)):
        for ec in ("L", "M"):
            text = "".join(rng.choice(alphabet) for _ in range(length))
            try:
                m = qr.make(text, ec)
            except ValueError:
                continue
            assert _decode(m) == text, (length, ec)
