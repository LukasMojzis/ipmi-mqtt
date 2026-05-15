import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest import mock

import ipmi_mqtt_core


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


class Reading:
    def __init__(self, name, value, units, unavailable=0):
        self.name = name
        self.value = value
        self.units = units
        self.unavailable = unavailable


def readings_from_elist(output):
    readings = []
    unit_map = {
        "temperature": "°C",
        "temperaturef": "°F",
        "fan": "RPM",
        "current": "A",
        "voltage": "V",
        "power": "W",
        "frequency": "Hz",
    }
    for sdr in ipmi_mqtt_core.dell_sdrs_from_elist(output):
        match = ipmi_mqtt_core.dell_matching_row(sdr, output)
        if match is None:
            continue
        readings.append(Reading(sdr["SUBCLASS"], ipmi_mqtt_core.numeric_sdr_value(match[4]), unit_map[sdr["SDR_CLASS"]]))
    return readings


class FakeSession:
    def __init__(self, readings=None, guid="guid", powerstate="on"):
        self._readings = list(readings or [])
        self._guid = guid
        self._powerstate = powerstate

    def sensor_readings(self):
        return list(self._readings)

    def targeted_sensor_readings(self, names):
        names = set(names)
        return [reading for reading in self._readings if reading.name in names]

    def guid(self):
        return self._guid

    def power_state(self):
        return self._powerstate

    def set_power(self, powerstate):
        self._powerstate = powerstate


class FakeBackend:
    def __init__(self, reading_sets=None, guid="guid"):
        self.reading_sets = list(reading_sets or [[]])
        self.guid = guid
        self.sessions = {}

    def session_for(self, server):
        key = str(server["IPMI_IP"])
        readings = self.reading_sets.pop(0) if self.reading_sets else []
        session = FakeSession(readings, guid=self.guid)
        self.sessions[key] = session
        return session


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

    def setUp(self):
        self.ipmi_mqtt.dell_discovery_cache.clear()
        self.ipmi_mqtt.sensor_update_engine.discovery_cache.clear()
        self.ipmi_mqtt.sensor_update_engine.value_cache.clear()
        self.ipmi_mqtt.sensor_update_engine.poll_count.clear()
        self.ipmi_mqtt.sensor_update_engine.backend = FakeBackend([readings_from_elist(DELL_SDR_OUTPUT)])
        self.ipmi_mqtt.poll_metrics = ipmi_mqtt_core.PollMetrics()

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

    def test_dell_parser_uses_entity_value_for_duplicate_sensor_names(self):
        current_sdr = {"SDR_CLASS": "voltage", "SUBCLASS": "Voltage", "VALUE": "10.2"}

        self.assertEqual(self.ipmi_mqtt.dell_ipmi_format(current_sdr, DELL_SDR_OUTPUT), "226")

    def test_numeric_sdr_value_preserves_decimals(self):
        self.assertEqual(self.ipmi_mqtt.numeric_sdr_value("0.60 Amps"), "0.60")

    def test_mqtt_safe_identifier_normalizes_guid_for_topic_ids(self):
        self.assertEqual(
            self.ipmi_mqtt.mqtt_safe_identifier("44454c4c-3200-1046-8033-b2c04f39354a"),
            "44454c4c-3200-1046-8033-b2c04f39354a",
        )
        self.assertEqual(
            self.ipmi_mqtt.mqtt_safe_identifier(" guid/with#+BAD\x00chars "),
            "guid_with_BAD_chars",
        )

    def test_get_guid_uses_sanitized_nodename_as_entity_prefix(self):
        server_config = [{
            "IPMI_NODENAME": "Node 01 / DELL-IDRAC6",
            "IPMI_IP": "192.0.2.10",
            "IPMI_USER": "root",
            "IPMI_PASSWORD": "secret",
        }]
        self.ipmi_mqtt.sensor_update_engine.backend = FakeBackend(guid="44454c4c320010468033b2c04f39354a")

        guid_dict, complete_guid_dict = self.ipmi_mqtt.get_guid(server_config)

        self.assertEqual(guid_dict["192.0.2.10"], "Node_01_DELL-IDRAC6")
        self.assertIn("Node_01_DELL-IDRAC6", complete_guid_dict)

    def test_dell_elist_autodiscovery_builds_visible_sdrs(self):
        sdrs = self.ipmi_mqtt.dell_sdrs_from_elist(DELL_SDR_OUTPUT)
        topics = {sdr["SDR_TOPIC"]: sdr for sdr in sdrs}

        self.assertIn("Ambient Temp", topics)
        self.assertIn("FAN MOD 1A RPM", topics)
        self.assertIn("Current 10.1", topics)
        self.assertIn("Current 10.2", topics)
        self.assertIn("Voltage 10.1", topics)
        self.assertIn("Voltage 10.2", topics)
        self.assertIn("System Level", topics)
        self.assertNotIn("Temp", topics)
        self.assertEqual(topics["Ambient Temp"]["SDR_CLASS"], "temperature")
        self.assertEqual(topics["FAN MOD 1A RPM"]["SDR_CLASS"], "fan")
        self.assertEqual(topics["Current 10.1"]["SDR_CLASS"], "current")
        self.assertEqual(topics["Current 10.1"]["SDR_NAME"], "Current 10.1")
        self.assertEqual(topics["Voltage 10.1"]["SDR_CLASS"], "voltage")
        self.assertEqual(topics["Voltage 10.1"]["SDR_NAME"], "Voltage 10.1")
        self.assertEqual(topics["System Level"]["SDR_CLASS"], "power")
        self.assertEqual(topics["System Level"]["SDR_NAME"], "System Level Power")

    def test_get_sdr_topic_derives_name_when_no_topic_map_exists(self):
        current_sdr = {"SUBCLASS": "Ambient Temp", "VALUE": "7.1", "SDR_CLASS": "temperature"}

        self.assertEqual(self.ipmi_mqtt.get_sdr_topic(current_sdr, {}), "Ambient_Temp")

    def test_missing_topics_defaults_to_read_only_topics(self):
        topic_dict, power_topic, switch_topic, sdr_topic_types, sdr_count = self.ipmi_mqtt.get_topics({})

        self.assertEqual(topic_dict, {})
        self.assertEqual(power_topic, "server_power_state")
        self.assertEqual(switch_topic, "")
        self.assertEqual(sdr_topic_types, {})
        self.assertEqual(sdr_count, 0)

    def test_current_and_power_discovery_payloads_include_units(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        client = Client()
        server_config = [{
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [
                {"SDR_TYPE": 1, "SDR_NAME": "dell_psu_current", "SDR_CLASS": "current", "SUBCLASS": "Current", "VALUE": "10.1"},
                {"SDR_TYPE": 2, "SDR_NAME": "dell_system_power", "SDR_CLASS": "power", "SUBCLASS": "System Level", "VALUE": "7.1"},
            ],
        }]
        guid_dict = {"192.0.2.10": "server-guid"}
        sdr_topic_types = {1: "dell_psu_current", 2: "dell_system_power"}

        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server_config[0],
            guid_dict,
            sdr_topic_types,
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        payloads = {topic: json.loads(payload) for topic, payload, _qos, _retain in client.published}
        self.assertEqual(client.published[0][0], "homeassistant/sensor/server-guid/dell_psu_current/state")
        self.assertEqual(client.published[1][0], "homeassistant/sensor/server-guid/dell_psu_current/config")
        self.assertEqual(client.published[2][0], "homeassistant/sensor/server-guid/dell_system_power/state")
        self.assertEqual(client.published[3][0], "homeassistant/sensor/server-guid/dell_system_power/config")
        current_payload = payloads["homeassistant/sensor/server-guid/dell_psu_current/config"]
        power_payload = payloads["homeassistant/sensor/server-guid/dell_system_power/config"]

        self.assertEqual(current_payload["device_class"], "current")
        self.assertEqual(current_payload["name"], "dell_psu_current")
        self.assertEqual(current_payload["unique_id"], "server-guid_sdr_dell_psu_current")
        self.assertEqual(current_payload["unit_of_meas"], "A")
        self.assertEqual(current_payload["state_class"], "measurement")
        self.assertEqual(current_payload["icon"], "mdi:current-ac")
        self.assertEqual(power_payload["device_class"], "power")
        self.assertEqual(power_payload["unit_of_meas"], "W")
        self.assertEqual(power_payload["state_class"], "measurement")
        self.assertEqual(power_payload["icon"], "mdi:flash")

        state_payloads = {topic: payload for topic, payload, _qos, _retain in client.published if topic.endswith("/state")}
        self.assertEqual(state_payloads["homeassistant/sensor/server-guid/dell_psu_current/state"], "0.60")
        self.assertEqual(state_payloads["homeassistant/sensor/server-guid/dell_system_power/state"], "287")

    def test_discovered_duplicate_sensor_uses_human_display_name(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

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
            "SDRS": [{
                "SDR_TYPE": "Voltage 10.1",
                "SDR_TOPIC": "Voltage 10.1",
                "SDR_NAME": "Voltage",
                "SDR_CLASS": "voltage",
                "SUBCLASS": "Voltage",
                "VALUE": "10.1",
            }],
        }]

        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server_config[0],
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        payloads = {topic: payload for topic, payload, _qos, _retain in client.published}
        voltage_payload = payloads["homeassistant/sensor/DELL-IDRAC6/Voltage_10_1/config"]

        self.assertEqual(voltage_payload["name"], "Voltage")
        self.assertEqual(voltage_payload["unique_id"], "DELL-IDRAC6_sdr_Voltage_10_1")
        self.assertEqual(voltage_payload["state_class"], "measurement")
        self.assertEqual(voltage_payload["icon"], "mdi:sine-wave")

    def test_fan_rpm_discovery_does_not_use_frequency_device_class(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

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
            "SDRS": [{
                "SDR_TYPE": "FAN MOD 1A RPM",
                "SDR_TOPIC": "FAN MOD 1A RPM",
                "SDR_NAME": "FAN MOD 1A RPM",
                "SDR_CLASS": "fan",
                "SUBCLASS": "FAN MOD 1A RPM",
                "VALUE": "7.1",
            }],
        }]

        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server_config[0],
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        payloads = {topic: payload for topic, payload, _qos, _retain in client.published}
        fan_payload = payloads["homeassistant/sensor/DELL-IDRAC6/FAN_MOD_1A_RPM/config"]

        self.assertNotIn("device_class", fan_payload)
        self.assertNotIn("state_class", fan_payload)
        self.assertEqual(fan_payload["unit_of_meas"], "RPM")
        self.assertEqual(fan_payload["icon"], "mdi:fan")

    def test_dell_publish_cycle_clears_stale_topics(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        client = Client()
        self.ipmi_mqtt.dell_discovery_cache["DELL-IDRAC6"] = {
            "homeassistant/sensor/DELL-IDRAC6/old_metric/config": "homeassistant/sensor/DELL-IDRAC6/old_metric/state"
        }

        server = {
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [{
                "SDR_TYPE": "Current 10.1",
                "SDR_TOPIC": "Current 10.1",
                "SDR_CLASS": "current",
                "SUBCLASS": "Current",
                "VALUE": "10.1",
            }],
        }

        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        self.assertIn(
            ("homeassistant/sensor/DELL-IDRAC6/old_metric/config", "", 2, True),
            client.published,
        )
        self.assertIn(
            ("homeassistant/sensor/DELL-IDRAC6/old_metric/state", "", 2, True),
            client.published,
        )
        self.assertEqual(
            self.ipmi_mqtt.dell_discovery_cache["DELL-IDRAC6"],
            {"homeassistant/sensor/DELL-IDRAC6/Current_10_1/config": "homeassistant/sensor/DELL-IDRAC6/Current_10_1/state"},
        )

    def test_unchanged_dell_sensor_cycle_does_not_republish(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        client = Client()
        server = {
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [{
                "SDR_TYPE": "System Level",
                "SDR_TOPIC": "System Level",
                "SDR_CLASS": "power",
                "SUBCLASS": "System Level",
                "VALUE": "7.1",
            }],
        }

        self.ipmi_mqtt.sensor_update_engine.backend = FakeBackend([
            readings_from_elist(DELL_SDR_OUTPUT),
            readings_from_elist(DELL_SDR_OUTPUT),
        ])
        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )
        client.published.clear()
        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        self.assertEqual(client.published, [])

    def test_changed_dell_sensor_cycle_publishes_next_value(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        client = Client()
        server = {
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [{
                "SDR_TYPE": "System Level",
                "SDR_TOPIC": "System Level",
                "SDR_CLASS": "power",
                "SUBCLASS": "System Level",
                "VALUE": "7.1",
            }],
        }
        changed_output = DELL_SDR_OUTPUT.replace("287 Watts", "301 Watts")

        self.ipmi_mqtt.sensor_update_engine.backend = FakeBackend([
            readings_from_elist(DELL_SDR_OUTPUT),
            readings_from_elist(changed_output),
        ])
        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )
        client.published.clear()
        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        self.assertIn(
            ("homeassistant/sensor/DELL-IDRAC6/System_Level/state", "301", 2, True),
            client.published,
        )

    def test_power_state_name_is_human_readable(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, json.loads(payload), qos, retain))
                return PublishResult()

        client = Client()

        self.ipmi_mqtt.power_sdr_initialization(
            [{"IPMI_NODENAME": "Node", "BRAND": "DELL", "IPMI_IP": "192.0.2.10"}],
            {"192.0.2.10": "Node"},
            "homeassistant/binary_sensor",
            "server_power_state",
            client,
            "mqtt.example",
        )

        payloads = {topic: payload for topic, payload, _qos, _retain in client.published}
        power_payload = payloads["homeassistant/binary_sensor/Node/server_power_state/config"]

        self.assertEqual(power_payload["name"], "Power State")

    def test_switch_discovery_is_opt_in(self):
        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))

        client = Client()

        self.ipmi_mqtt.switch_sdr_initialization(
            [{"IPMI_NODENAME": "Node", "BRAND": "DELL", "IPMI_IP": "192.0.2.10"}],
            {"192.0.2.10": "Node"},
            "homeassistant/switch",
            "",
            "homeassistant/binary_sensor",
            "server_power_state",
            client,
            "mqtt.example",
        )

        self.assertEqual(client.published, [])

    def test_default_mqtt_client_id_is_unique(self):
        config = {
            "MQTT": {
                "MQTT_ip": "mqtt.example",
                "MQTT_USER": "user",
                "MQTT_PW": "pass",
                "MQTT_ID": "ipmi-mqtt-server",
                "TIME_PERIOD": 1,
                "HA_BINARY": "homeassistant/binary_sensor",
                "HA_SENSOR": "homeassistant/sensor",
            }
        }

        with mock.patch.object(self.ipmi_mqtt.socket, "gethostname", return_value="host"), \
                mock.patch.object(self.ipmi_mqtt.os, "getpid", return_value=123):
            mqtt_config = self.ipmi_mqtt.get_mqtt(config)

        self.assertEqual(mqtt_config[-1], "ipmi-mqtt-host-123")

    def test_high_priority_cycle_publishes_power_only(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        first = readings_from_elist(DELL_SDR_OUTPUT)
        changed = readings_from_elist(DELL_SDR_OUTPUT.replace("287 Watts", "301 Watts").replace("4920 RPM", "4800 RPM"))
        self.ipmi_mqtt.sensor_update_engine.backend = FakeBackend([first, changed])
        client = Client()
        server = {
            "IPMI_NODENAME": "DELL-IDRAC6",
            "BRAND": "DELL",
            "IPMI_IP": "192.0.2.10",
            "SDRS": [
                {"SDR_TYPE": "System Level", "SDR_TOPIC": "System Level", "SDR_CLASS": "power", "SUBCLASS": "System Level", "VALUE": "7.1"},
                {"SDR_TYPE": "FAN MOD 1A RPM", "SDR_TOPIC": "FAN MOD 1A RPM", "SDR_CLASS": "fan", "SUBCLASS": "FAN MOD 1A RPM", "VALUE": "7.1"},
            ],
        }

        self.ipmi_mqtt.publish_dell_sensor_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )
        client.published.clear()
        self.ipmi_mqtt.publish_dell_high_priority_cycle(
            server,
            {"192.0.2.10": "DELL-IDRAC6"},
            {},
            "homeassistant/sensor",
            client,
            "mqtt.example",
        )

        topics = [topic for topic, _payload, _qos, _retain in client.published]
        self.assertIn("homeassistant/sensor/DELL-IDRAC6/System_Level/state", topics)
        self.assertNotIn("homeassistant/sensor/DELL-IDRAC6/FAN_MOD_1A_RPM/state", topics)

    def test_poll_metrics_publish_state_topics(self):
        class PublishResult:
            def wait_for_publish(self):
                return True

        class Client:
            def __init__(self):
                self.published = []

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((topic, payload, qos, retain))
                return PublishResult()

        client = Client()
        self.ipmi_mqtt.poll_metrics.record(1.25, 0.25)

        self.ipmi_mqtt.publish_poll_metrics("homeassistant/sensor", client, "mqtt.example")

        payloads = {topic: payload for topic, payload, _qos, _retain in client.published}
        self.assertEqual(payloads["homeassistant/sensor/ipmi_mqtt/poll_cycles/state"], "1")
        self.assertEqual(payloads["homeassistant/sensor/ipmi_mqtt/poll_overruns/state"], "1")
        self.assertEqual(payloads["homeassistant/sensor/ipmi_mqtt/poll_last_cycle_seconds/state"], "1.250")


class CoreBackendTest(unittest.TestCase):
    def test_pyghmi_backend_reuses_and_reconnects_session(self):
        class Command:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        backend = ipmi_mqtt_core.PyghmiBackend(command_factory=Command)
        server = {"IPMI_IP": "192.0.2.10", "IPMI_USER": "root", "IPMI_PASSWORD": "secret"}

        first = backend.session_for(server)
        second = backend.session_for(server)
        reconnected = backend.reconnect(server)

        self.assertIs(first, second)
        self.assertIsNot(first, reconnected)

    def test_engine_tracks_discovery_and_fallback_poll_count(self):
        class Backend:
            def session_for(self, server):
                raise AssertionError("not used by direct reading test")

        engine = ipmi_mqtt_core.SensorUpdateEngine(Backend(), fallback_interval=2)
        readings = [{
            "server_identifier": "server",
            "topic": "Ambient_Temp",
            "value": "20",
            "name": "Ambient Temp",
            "class": "temperature",
            "source": {},
        }]

        changed, stale = engine.dell_changes_from_readings("server", readings)
        unchanged, stale_second = engine.dell_changes_from_readings("server", readings)

        self.assertEqual(changed, readings)
        self.assertEqual(unchanged, [])
        self.assertEqual(stale, set())
        self.assertEqual(stale_second, set())
        self.assertEqual(engine.poll_count["server"], 2)

    def test_fixed_rate_timer_uses_absolute_deadlines(self):
        now = [100.0]
        timer = ipmi_mqtt_core.FixedRateTimer(5, clock=lambda: now[0], sleeper=lambda delay: None)

        now[0] = 102.0
        self.assertEqual(timer.delay_until_next(), 3.0)
        now[0] = 106.2
        self.assertAlmostEqual(timer.delay_until_next(), 3.8)

    def test_fixed_rate_timer_reports_overrun(self):
        timer = ipmi_mqtt_core.FixedRateTimer(1, clock=lambda: 0, sleeper=lambda delay: None)

        self.assertEqual(timer.overrun(10.0, 10.5), 0)
        self.assertAlmostEqual(timer.overrun(10.0, 12.25), 1.25)


class ContainerWorkflowTest(unittest.TestCase):
    def test_container_workflow_tags_branch_release_and_default_latest(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github" / "workflows" / "container-image.yml").read_text()

        self.assertIn('branches:\n      - "**"', workflow)
        self.assertIn("type=ref,event=branch", workflow)
        self.assertIn("type=semver,pattern={{version}}", workflow)
        self.assertIn("type=raw,value=latest,enable={{is_default_branch}}", workflow)
        self.assertIn("push: ${{ github.event_name != 'pull_request' }}", workflow)


if __name__ == "__main__":
    unittest.main()
