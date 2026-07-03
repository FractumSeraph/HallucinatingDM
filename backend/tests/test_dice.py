import pytest

from app.services.dice import DiceError, roll, roll_d20


def test_simple_roll():
    r = roll("2d6+3")
    assert len(r.rolls) == 2
    assert all(1 <= f <= 6 for f in r.rolls)
    assert r.modifier == 3
    assert r.total == sum(r.rolls) + 3


def test_bare_d20():
    r = roll("d20")
    assert len(r.rolls) == 1
    assert 1 <= r.total <= 20


def test_multi_term():
    r = roll("1d8+2d6-1")
    assert len(r.rolls) == 3
    assert r.modifier == -1
    assert r.total == sum(r.rolls) - 1


def test_keep_highest():
    r = roll("4d6kh3")
    assert len(r.rolls) == 4
    assert len(r.kept) == 3
    assert sorted(r.kept, reverse=True) == sorted(r.rolls, reverse=True)[:3]
    assert r.total == sum(r.kept)


def test_keep_lowest():
    r = roll("2d20kl1")
    assert len(r.rolls) == 2
    assert r.total == min(r.rolls)


@pytest.mark.parametrize(
    "bad", ["", "banana", "2d", "d1", "0d6", "999d6+1d0", "4d6kh5", "2d6 3"]
)
def test_invalid_expressions(bad):
    with pytest.raises(DiceError):
        roll(bad)


def test_case_and_whitespace():
    r = roll(" 2D6 + 3 ")
    assert r.expression == "2d6+3"


def test_advantage():
    chosen, faces = roll_d20("adv")
    assert chosen == max(faces)
    assert len(faces) == 2
    chosen, faces = roll_d20("dis")
    assert chosen == min(faces)
    chosen, faces = roll_d20("none")
    assert [chosen] == faces
