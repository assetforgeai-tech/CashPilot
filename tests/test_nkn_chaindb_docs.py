from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nkn_guide_documents_private_snapshot_fallback_and_identity_boundaries():
    text = (ROOT / "docs" / "guides" / "nkn.md").read_text(encoding="utf-8")
    for phrase in (
        "private R2",
        "latest.json",
        "immutable",
        "fallback",
        "ChainDB/",
        "config.json",
        "wallet.json",
        "rollback",
        "new NKN nodes",
        "install-nkn-host-helper.sh",
        "root:root",
        "Existing inner Docker\n  nodes are never recreated just to change DNS",
    ):
        assert phrase in text


def test_active_context_records_snapshot_live_closeout_and_protected_matrix():
    text = (ROOT / "docs" / "ACTIVE_CONTEXT.md").read_text(encoding="utf-8")
    assert "ChainDB snapshot" in text
    assert "PROTECTED_DONE" in text
    assert "test-sing" in text
    assert "publisher VPS" in text
    assert "v1.6.2" in text
    assert "bb52dea" in text
    assert "4909468c68b1d5c7b186b0596e966f3f28db4325588725e2162ee0f09db90f03" in text
    assert "PERSIST_FINISHED" in text
    assert "active (waiting)" in text
    assert "no live mutation yet" not in text
