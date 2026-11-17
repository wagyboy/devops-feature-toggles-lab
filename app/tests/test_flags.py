"""Unit tests for flag evaluation (no HTTP)."""
from conftest import set_flag

from shop.flags import bucket, is_on
from shop.metrics import overlap, wilson

ALICE = {"id": 7, "login": "alice"}


def test_bucket_is_stable_and_in_range():
    assert bucket("quick_buy", 7) == bucket("quick_buy", 7)
    assert all(0 <= bucket("quick_buy", i) < 100 for i in range(500))


def test_bucket_splits_roughly_half_at_50_percent():
    on = sum(bucket("quick_buy", i) < 50 for i in range(2000))
    assert 900 < on < 1100


def test_experiments_are_independent():
    # salting with the flag name: knowing a user's quick_buy group says nothing about stock_badge
    same = sum((bucket("quick_buy", i) < 50) == (bucket("stock_badge", i) < 50) for i in range(2000))
    assert 900 < same < 1100


def test_anonymous_users_never_get_a_variant(app):
    with app.test_request_context():
        set_flag(app, "quick_buy", rollout=100)
        assert is_on("quick_buy", None) is False


def test_rollout_0_and_100(app):
    with app.test_request_context():
        set_flag(app, "quick_buy", rollout=100)
        assert is_on("quick_buy", ALICE) is True
    with app.test_request_context():
        set_flag(app, "quick_buy", rollout=0)
        assert is_on("quick_buy", ALICE) is False


def test_kill_switch_beats_everything(app, tmp_path):
    flags = tmp_path / "flags.json"
    flags.write_text('{"quick_buy": {"description": "x", "enabled": true, "rollout": 100, "force_on": ["alice"]},'
                     ' "stock_badge": {"description": "y", "enabled": true, "rollout": 0}}')
    app.config["FLAGS_FILE"] = str(flags)
    with app.test_request_context():
        assert is_on("quick_buy", ALICE) is True
    with app.test_request_context():
        set_flag(app, "quick_buy", enabled=False, rollout=100)
        assert is_on("quick_buy", ALICE) is False   # even though alice is in force_on


def test_force_lists_pin_test_accounts(app, tmp_path):
    flags = tmp_path / "flags.json"
    flags.write_text('{"quick_buy": {"description": "x", "enabled": true, "rollout": 0, "force_on": ["Alice"]},'
                     ' "stock_badge": {"description": "y", "enabled": true, "rollout": 100, "force_off": ["alice"]}}')
    app.config["FLAGS_FILE"] = str(flags)
    with app.test_request_context():
        assert is_on("quick_buy", ALICE) is True      # case-insensitive login match
        assert is_on("stock_badge", ALICE) is False


def test_wilson_interval_matches_known_values():
    # reference values for the 95% Wilson score interval
    assert wilson(0, 10) == (0.0, 27.8)
    assert wilson(5, 10) == (23.7, 76.3)
    assert wilson(10, 10) == (72.2, 100.0)
    assert wilson(0, 0) is None


def test_overlap_says_when_the_data_cannot_tell_variants_apart():
    assert overlap((10.0, 40.0), (30.0, 60.0)) is True
    assert overlap((10.0, 20.0), (30.0, 60.0)) is False
    assert overlap(None, (30.0, 60.0)) is None
