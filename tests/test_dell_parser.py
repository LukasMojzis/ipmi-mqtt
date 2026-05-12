import importlib.util
import json
import pathlib
import sys
import types
import unittest


DELL_SDR_OUTPUT = """Temp             | 01h | ns  |  3.1 | Disabled
Temp             | 02h | ns  |  3.2 | Disabled
Temp             | 05h | ns  | 10.1 | Disabled
Temp             | 06h | ns  | 10.2 | Disabled
Ambient Temp     | 0Eh | ok  |  7.1 | 20 degrees C
Planar Temp      | 0Fh | ns  |  7.1 | Disabled
FAN MOD 1A RPM   | 30h | ok  |  7.1 | 4920 RPM
FAN MOD 1B RPM   | 31h | ok  |  7.1 | 4920 RPM
FAN MOD 2A RPM   | 32h | ok  |  7.1 | 4920 RPM
FAN MOD 2B RPM   | 33h | ok  |  7.1 | 4920 RPM
FAN MOD 3A RPM   | 34h | ok  |  7.1 | 4920 RPM
FAN MOD 3B RPM   | 35h | ok  |  7.1 | 4920 RPM
FAN MOD 4A RPM   | 36h | ok  |  7.1 | 2400 RPM
Current          | 94h | ok  | 10.1 | 0.60 Amps
Current          | 95h | ok  | 10.2 | 0.60 Amps
Voltage          | 96h | ok  | 10.1 | 226 Volts
Voltage          | 97h | ok  | 10.2 | 226 Volts
System Level     | 98h | ok  |  7.1 | 287 Watts
Temp             | 0Ah | ns  |  8.1 | Disabled
Temp             | 0Bh | ns  |  8.1 | Disabled
Temp             | 0Ch | ns  |  8.1 | Disabled
FAN MOD 4B RPM   | 37h | ok  |  7.1 | 2400 RPM
FAN MOD 5B RPM   | 3Ah | ok  |  7.1 | 2400 RPM
FAN MOD 5A RPM   | 3Bh | ok  |  7.1 | 2400 RPM
Ambient Temp     | 07h | ns  | 10.1 | Disabled
Ambient Temp     | 08h | ns  | 10.2 | Disabled"""


def load_ipmi_mqtt_module():
    repo_root = pathlib.Path(__file__).resolve().parents[1]

    yaml_module = types.ModuleType("yaml")
    yaml_module.safe_load = lambda configuration: {}
    sys.modules["yaml"] = yaml_module

    daemon_module = types.ModuleType("daemon")
    daemon_module.DaemonContext = object
    sys.modules["daemon"] = daemon_module

    paho_module = types.ModuleType("paho")
    mqtt_package = types.ModuleType("paho.mqtt")
    mqtt_client_module = types.ModuleType("paho.mqtt.client")
    mqtt_client_module.Client = object
    mqtt_package.client = mqtt_client_module
    paho_module.mqtt = mqtt_package
    sys.modules["paho"] = paho_module
    sys.modules["paho.mqtt"] = mqtt_package
    sys.modules["paho.mqtt.client"] = mqtt_client_module

    original_argv = sys.argv
    sys.argv = ["ipmi-mqtt.py"]
    try:
        spec = importlib.util.spec_from_file_location("ipmi_mqtt_under_test", repo_root / "ipmi-mqtt.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = original_argv


class DellParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ipmi_mqtt = load_ipmi_mqtt_module()

    def test_dell_parser_extracts_numeric_values(self):
        cases = (
            ("temperature", "Ambient Temp", "20"),
            ("fan", "FAN MOD 1A RPM", "4920"),
            ("fan", "FAN MOD 4B RPM", "2400"),
            ("current", "Current", "0.60"),
            ("voltage", "Voltage", "226"),
            ("power", "System Level", "287"),
        )

        for sdr_class, subclass, expected in cases:
            with self.subTest(subclass=subclass):
                current_sdr = {"SDR_CLASS": sdr_class, "SUBCLASS": subclass}
                self.assertEqual(self.ipmi_mqtt.dell_ipmi_format(current_sdr, DELL_SDR_OUTPUT), expected)

    def test_dell_parser_returns_empty_value_for_disabled_sensor(self):
        current_sdr = {"SDR_CLASS": "temperature", "SUBCLASS": "Temp"}

        self.assertEqual(self.ipmi_mqtt.dell_ipmi_format(current_sdr, DELL_SDR_OUTPUT), "")

    def test_numeric_sdr_value_preserves_decimals(self):
        self.assertEqual(self.ipmi_mqtt.numeric_sdr_value("0.60 Amps"), "0.60")

    def test_current_and_power_discovery_payloads_include_units(self):
        class PublishResult:
            wait_for_publish = True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, json.loads(payload), qos, retain))
                return PublishResult()

        client = Client()
        server_config = [{
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [
                {"SDR_TYPE": 1, "SDR_CLASS": "current"},
                {"SDR_TYPE": 2, "SDR_CLASS": "power"},
            ],
        }]
        guid_dict = {"192.0.2.10": "server-guid"}
        sdr_topic_types = {1: "dell_psu_current", 2: "dell_system_power"}

        self.ipmi_mqtt.sensor_sdr_initialization(
            server_config,
            guid_dict,
            sdr_topic_types,
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        payloads = {topic: payload for topic, payload, _qos, _retain in client.published}
        current_payload = payloads["homeassistant/sensor/server-guid_dell_psu_current/config"]
        power_payload = payloads["homeassistant/sensor/server-guid_dell_system_power/config"]

        self.assertEqual(current_payload["device_class"], "current")
        self.assertEqual(current_payload["unit_of_meas"], "A")
        self.assertEqual(power_payload["device_class"], "power")
        self.assertEqual(power_payload["unit_of_meas"], "W")


if __name__ == "__main__":
    unittest.main()
