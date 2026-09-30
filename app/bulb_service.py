import time
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


import socket
from concurrent.futures import ThreadPoolExecutor

def discover_bulb_ip(base_subnet="192.168.0", port=6668, timeout=0.15):
    """Fast concurrent scan to find the bulb IP if DHCP reassigns it."""
    found_ips = []
    def check_ip(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if s.connect_ex((ip, port)) == 0:
                found_ips.append(ip)
            s.close()
        except Exception:
            pass

    targets = [f"{base_subnet}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(check_ip, targets)

    return found_ips[0] if found_ips else None


class TuyaBulbAdapter(BaseBulbAdapter):
    """
    Physical smart bulb adapter using TinyTuya (tested with Wipro 9W RGB, protocol 3.5).
    Includes socket verification, subnet discovery, and non-blocking offline resilience.
    """
    def __init__(self):
        self.dev_id = settings.BULB_DEVICE_ID
        self.ip = settings.BULB_IP
        self.local_key = settings.BULB_LOCAL_KEY
        self.version = float(settings.BULB_PROTOCOL)
        self.auto_discover = True
        self._last_offline_check = 0.0
        self._is_online = False
        self._init_device()

    def _init_device(self):
        self.device = tinytuya.BulbDevice(
            self.dev_id,
            self.ip,
            self.local_key,
            version=self.version
        )
        self.device.set_socketPersistent(False)
        self.device.set_socketTimeout(2)

    def verify_connection(self) -> bool:
        """Fast check if bulb is reachable at self.ip; auto-scans if DHCP reassigned."""
        now = time.time()
        # If recently checked as offline (< 5s ago), don't stall with repeated scans
        if not self._is_online and (now - self._last_offline_check < 5.0):
            return False

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            reachable = (s.connect_ex((self.ip, 6668)) == 0)
            s.close()
        except Exception:
            reachable = False

        if not reachable and self.auto_discover:
            logger.info(f"[TuyaBulb] Bulb not responding at {self.ip}. Auto-scanning local network...")
            new_ip = discover_bulb_ip()
            if new_ip:
                logger.info(f"[TuyaBulb] Discovered bulb at new IP: {new_ip}")
                self.ip = new_ip
                self._init_device()
                reachable = True
            else:
                self._last_offline_check = now
                self._is_online = False
                logger.warning("[TuyaBulb] Bulb not found on local network. Is physical wall switch ON?")
                return False

        self._is_online = reachable
        return reachable

    def get_state(self) -> Dict[str, Any]:
        if not self.verify_connection():
            return {"power": False, "error": "Bulb unreachable / physical switch is OFF"}
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
        if not self.verify_connection():
            return False
        try:
            res = self.device.set_value("20", power)
            logger.info(f"[TuyaBulb] Power set to {power} (result: {res})")
            return True
        except Exception as e:
            logger.error(f"[TuyaBulb] Failed to set power: {e}")
            return False

    def set_color(self, color_name: str) -> bool:
        if not self.verify_connection():
            return False
        hex_val = COLOR_HEX_MAP.get(color_name.lower(), COLOR_HEX_MAP["red"])
        try:
            payload = {
                "20": True,
                "21": "colour",
                "24": hex_val
            }
            res = self.device.set_multiple_values(payload)
            logger.info(f"[TuyaBulb] Color set to {color_name} (hex: {hex_val}, result: {res})")
            return True
        except Exception as e:
            logger.error(f"[TuyaBulb] Failed to set color {color_name}: {e}")
            return False

    def turn_off(self) -> bool:
        return self.set_power(False)

    def restore(self, snapshot: Optional[Dict[str, Any]]) -> bool:
        if not self.verify_connection():
            return False
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
            self.device.set_multiple_values(dps)
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
