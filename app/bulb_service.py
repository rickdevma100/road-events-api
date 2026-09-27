import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import tinytuya
from app.config import settings

logger = logging.getLogger("bulb_service")

# Preset 12-char hex values for DP 24 (HHHHSSSSVVVV):
# Hue 0-360 mapped to 0x0000-0x0168, Sat 0-1000 to 0x03e8, Val 0-1000 to 0x03e8
COLOR_HEX_MAP = {
    "red": "000003e803e8",     # Hue: 0°
    "yellow": "003303e803e8",  # Hue: 51°
    "green": "007803e803e8",   # Hue: 120°
    "blue": "00f003e803e8",    # Hue: 240°
}

class BaseBulbAdapter(ABC):
    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Reads current state of the bulb."""
        pass

    @abstractmethod
    def set_power(self, power: bool) -> bool:
        """Sets power ON or OFF."""
        pass

    @abstractmethod
    def set_color(self, color_name: str) -> bool:
        """Sets bulb color ('green', 'yellow', 'red')."""
        pass

    @abstractmethod
    def turn_off(self) -> bool:
        """Turns off the bulb."""
        pass

    @abstractmethod
    def restore(self, snapshot: Optional[Dict[str, Any]]) -> bool:
        """Restores snapshot or turns off."""
        pass


class MockBulbAdapter(BaseBulbAdapter):
    """
    In-memory mock bulb adapter for unit tests and local development.
    """
    def __init__(self):
        self.power = False
        self.color = "off"
        self.brightness = 1000
        self.call_history = []

    def get_state(self) -> Dict[str, Any]:
        return {
            "power": self.power,
            "color": self.color,
            "brightness": self.brightness
        }

    def set_power(self, power: bool) -> bool:
        self.power = power
        self.call_history.append(("set_power", power))
        logger.info(f"[MockBulb] Power set to {power}")
        return True

    def set_color(self, color_name: str) -> bool:
        self.power = True
        self.color = color_name
        self.call_history.append(("set_color", color_name))
        logger.info(f"[MockBulb] Color set to {color_name}")
        return True

    def turn_off(self) -> bool:
        self.power = False
        self.color = "off"
        self.call_history.append(("turn_off",))
        logger.info("[MockBulb] Turned OFF")
        return True

    def restore(self, snapshot: Optional[Dict[str, Any]]) -> bool:
        if snapshot and snapshot.get("power") is not None:
            self.power = snapshot.get("power", False)
            self.color = snapshot.get("color", "off")
            self.brightness = snapshot.get("brightness", 1000)
            self.call_history.append(("restore", snapshot))
            logger.info(f"[MockBulb] Restored snapshot: {snapshot}")
        else:
            self.turn_off()
        return True


class TuyaBulbAdapter(BaseBulbAdapter):
    """
    Physical smart bulb adapter using TinyTuya (tested with Wipro 9W RGB, protocol 3.5).
    """
    def __init__(self):
        self.device = tinytuya.BulbDevice(
            dev_id=settings.BULB_DEVICE_ID,
            address=settings.BULB_IP,
            local_key=settings.BULB_LOCAL_KEY,
            version=float(settings.BULB_PROTOCOL)
        )
        self.device.set_socketPersistent(True)
        self.device.set_socketTimeout(3)

    def get_state(self) -> Dict[str, Any]:
        try:
            status = self.device.status()
            dps = status.get("dps", {}) if isinstance(status, dict) else {}
            return {
                "power": dps.get("20", False),
                "mode": dps.get("21", "white"),
                "brightness": dps.get("22", 1000),
                "color_hex": dps.get("24", "")
            }
        except Exception as e:
            logger.error(f"[TuyaBulb] Error reading status: {e}")
            return {"power": False, "error": str(e)}

    def set_power(self, power: bool) -> bool:
        try:
            payload = self.device.generate_payload(tinytuya.CONTROL, {"20": power})
            self.device.send(payload)
            logger.info(f"[TuyaBulb] Power set to {power}")
            return True
        except Exception as e:
            logger.error(f"[TuyaBulb] Failed to set power: {e}")
            return False

    def set_color(self, color_name: str) -> bool:
        hex_val = COLOR_HEX_MAP.get(color_name.lower(), COLOR_HEX_MAP["red"])
        try:
            # Set switch=True, mode='colour', and colour_data_v2
            payload = self.device.generate_payload(tinytuya.CONTROL, {
                "20": True,
                "21": "colour",
                "24": hex_val
            })
            self.device.send(payload)
            logger.info(f"[TuyaBulb] Color set to {color_name} (hex: {hex_val})")
            return True
        except Exception as e:
            logger.error(f"[TuyaBulb] Failed to set color {color_name}: {e}")
            return False

    def turn_off(self) -> bool:
        return self.set_power(False)

    def restore(self, snapshot: Optional[Dict[str, Any]]) -> bool:
        if not snapshot or not snapshot.get("power", False):
            return self.turn_off()
        try:
            dps = {"20": snapshot.get("power", False)}
            if "color_hex" in snapshot and snapshot["color_hex"]:
                dps["21"] = "colour"
                dps["24"] = snapshot["color_hex"]
            elif "mode" in snapshot:
                dps["21"] = snapshot["mode"]
                if "brightness" in snapshot:
                    dps["22"] = snapshot["brightness"]
            payload = self.device.generate_payload(tinytuya.CONTROL, dps)
            self.device.send(payload)
            return True
        except Exception as e:
            logger.error(f"[TuyaBulb] Failed to restore snapshot: {e}")
            return self.turn_off()


_adapter_instance: Optional[BaseBulbAdapter] = None

def get_bulb_adapter() -> BaseBulbAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        if settings.BULB_ADAPTER.lower() == "tuya":
            _adapter_instance = TuyaBulbAdapter()
        else:
            _adapter_instance = MockBulbAdapter()
    return _adapter_instance

def set_bulb_adapter(adapter: BaseBulbAdapter):
    global _adapter_instance
    _adapter_instance = adapter
