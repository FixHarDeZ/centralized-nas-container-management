import os

import db
import scheduler


def test_expiry_job_purges_expired(data_dir):
    tid = db.add_title("old", "Old", "", 1, 1, "u")
    open(db.cbz_path(tid), "wb").write(b"x")
    with db._connect() as conn:
        conn.execute(
            "UPDATE titles SET expires_at='2000-01-01T00:00:00+07:00' WHERE id=?",
            (tid,),
        )
    fresh = db.add_title("fresh", "Fresh", "", 1, 1, "u")

    assert scheduler.expiry_job() == 1
    assert db.get_title(tid)["status"] == "deleted"
    assert not os.path.exists(db.cbz_path(tid))
    assert db.get_title(fresh)["status"] == "new"
