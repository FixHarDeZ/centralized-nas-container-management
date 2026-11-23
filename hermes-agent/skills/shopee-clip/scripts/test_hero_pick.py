"""hero_pick ranking: sharpest wins, skin breaks a tie, dark/flash frames never win."""
import importlib.util
import os

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "hero_pick", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero_pick.py"))
hp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hp)


def row(sharp, skin, bad=""):
    return {"sharp": sharp, "skin": skin, "bad": bad}


def test_sharpest_wins():
    assert hp.rank([row(100, 0.1), row(300, 0.3), row(150, 0.0)]) == 1


def test_tie_goes_to_less_skin():
    assert hp.rank([row(300, 0.40), row(280, 0.05), row(100, 0.0)]) == 1


def test_bad_frames_never_win():
    assert hp.rank([row(900, 0.0, "flash"), row(100, 0.2)]) == 1
    assert hp.rank([row(900, 0.0, "dark")]) is None


def test_sharpness_and_skin_measures():
    flat = np.full((64, 64), 128, np.float32)
    noisy = flat + np.random.default_rng(0).normal(0, 30, flat.shape).astype(np.float32)
    assert hp.sharpness(noisy) > 100 * (hp.sharpness(flat) + 1)
    skin = np.zeros((10, 10, 3), np.uint8)
    skin[:] = (224, 172, 150)
    wall = np.zeros((10, 10, 3), np.uint8)
    wall[:] = (90, 140, 200)
    assert hp.skin(skin) > 0.9 and hp.skin(wall) < 0.05
