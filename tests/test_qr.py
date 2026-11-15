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


@pytest.mark.parametrize("ec", ["L", "M"])
def test_decodes_with_opencv(ec):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from setu import config, state as S
    s = S.new_state("203.0.113.7")
    d = S.add_device(s, "alice-phone")
    texts = ["https://github.com/AnuragRoy485/setu", "x" * 120, config.render_client_conf(s, d)]
    for text in texts:
        m = qr.make(text, ec)
        n, sc, b = len(m), 8, 4
        img = np.full(((n + 2 * b) * sc,) * 2, 255, np.uint8)
        for y in range(n):
            for x in range(n):
                if m[y][x]:
                    img[(y + b) * sc:(y + b + 1) * sc, (x + b) * sc:(x + b + 1) * sc] = 0
        got, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        assert got == text
