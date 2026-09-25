"""Import examples so coverage measures them. Docs stay typecheck+exec in test_docs."""

import data_delivery_after
import data_delivery_before
import quickstart
import smoke
import symlink_copy


def test_examples_import() -> None:
    assert quickstart.curate
    assert data_delivery_before.pull
    assert data_delivery_after.DownloadedDelivery
    smoke.main()
    symlink_copy.main()
