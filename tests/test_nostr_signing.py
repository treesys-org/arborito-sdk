"""Nostr signing + archive id parity tests."""

from __future__ import annotations

from arborito_sdk.bip340 import pubkey_gen, schnorr_sign, schnorr_verify
from arborito_sdk.nostr_publish import sign_event
from arborito_sdk.publisher_store import create_nostr_pair
from arborito_sdk.quiz_v2 import _build_leaf, _slugify, clean_lesson_text


def test_slugify_strips_accents_like_arborito():
    assert _slugify("es/lección") == "es-leccion"
    assert _slugify("ES/Lessons") == "es-lessons"


def test_leaf_id_matches_arborito_full_zip_path():
    entries = {"01-intro/hola.md": b"@info\ntitle: Hola\n@/info\n\nBody\n"}
    leaf = _build_leaf(
        relative_path="01-intro/hola.md",
        lang_entries=entries,
        lang="es",
        parent_id="branch-x",
        parent_path="Course",
    )
    assert leaf["id"] == "leaf-es-lessons-es-01-intro-hola-md"
    assert leaf["archive_entry"] == "lessons/es/01-intro/hola.md"


def test_clean_lesson_text_strips_info_and_quiz():
    raw = "@info\ntitle: T\n@/info\n\nHello\n\n@quiz\nconcept: c\n@/quiz\n"
    assert clean_lesson_text(raw) == "Hello"


def test_bip340_vector_keygen_and_sign():
    # BIP-340 test vector index 0 (keygen + deterministic aux).
    seckey = bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000003")
    pubkey = pubkey_gen(seckey)
    assert pubkey.hex() == "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9".lower()
    aux = bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000")
    msg = bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000")
    sig = schnorr_sign(msg, seckey, aux)
    assert schnorr_verify(msg, pubkey, sig)
    assert (
        sig.hex().upper()
        == "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
        "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"
    )


def test_sign_event_and_create_pair():
    pair = create_nostr_pair()
    assert len(pair["pub"]) == 64
    assert len(pair["priv"]) == 64
    ev = sign_event(
        {"kind": 1, "created_at": 1_700_000_000, "tags": [["d", "t"]], "content": "hi"},
        pair["priv"],
    )
    assert ev["pubkey"] == pair["pub"]
    assert len(ev["id"]) == 64
    assert len(ev["sig"]) == 128
    assert schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["sig"]))
