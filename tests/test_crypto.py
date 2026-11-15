import base64

from setu import crypto


def test_rfc7748_vectors():
    k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
    u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
    assert crypto.x25519(k, u).hex() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
    alice = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    assert crypto.x25519(alice, crypto._BASE).hex() == \
        "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"


def test_diffie_hellman_agrees():
    a, b = crypto.genkey(), crypto.genkey()
    sa = crypto.x25519(crypto.unb64(a), crypto.unb64(crypto.pubkey(b)))
    sb = crypto.x25519(crypto.unb64(b), crypto.unb64(crypto.pubkey(a)))
    assert sa == sb


def test_key_format():
    k = crypto.genkey()
    assert len(base64.b64decode(k)) == 32 and len(k) == 44 and k.endswith("=")
    assert crypto.valid_key(k) and not crypto.valid_key("nope")


def test_matches_cryptography_library_if_present():
    try:
        from cryptography.hazmat.primitives import serialization as s
        from cryptography.hazmat.primitives.asymmetric import x25519
    except ImportError:
        return
    for _ in range(10):
        p = crypto.genkey()
        ref = x25519.X25519PrivateKey.from_private_bytes(base64.b64decode(p)).public_key()
        raw = ref.public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
        assert base64.b64encode(raw).decode() == crypto.pubkey(p)
