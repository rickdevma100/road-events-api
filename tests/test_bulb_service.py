import pytest
from app.bulb_service import MockBulbAdapter, get_bulb_adapter, set_bulb_adapter

def test_mock_bulb_adapter():
    bulb = MockBulbAdapter()
    assert bulb.get_state()["power"] is False

    bulb.set_color("green")
    assert bulb.get_state()["power"] is True
    assert bulb.get_state()["color"] == "green"

    bulb.set_color("yellow")
    assert bulb.get_state()["color"] == "yellow"

    bulb.set_color("red")
    assert bulb.get_state()["color"] == "red"

    bulb.turn_off()
    assert bulb.get_state()["power"] is False

    # Snapshot restore
    snapshot = {"power": True, "color": "green", "brightness": 800}
    bulb.restore(snapshot)
    assert bulb.get_state()["power"] is True
    assert bulb.get_state()["color"] == "green"
