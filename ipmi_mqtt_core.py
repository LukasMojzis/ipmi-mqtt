import logging
import math
import re
import time


def mqtt_safe_identifier(identifier):
    identifier = re.sub(r'[^A-Za-z0-9_-]+', '_', str(identifier).strip())
    identifier = re.sub(r'_+', '_', identifier).strip('_')
    return identifier


def mqtt_path_segment(identifier):
    return mqtt_safe_identifier(identifier)


def ha_unique_id(*parts):
    return mqtt_safe_identifier("_".join(str(part) for part in parts if str(part) != ""))


def mqtt_display_name(value):
    value = str(value).strip()
    if value == "":
        return value
    return re.sub(r'[_-]+', ' ', value).title()


def power_display_name(power_topic):
    if power_topic == "server_power_state":
        return "Power State"
    return mqtt_display_name(power_topic)


def sdr_display_name(sensor_name, sdr_class):
    sensor_name = str(sensor_name).strip()
    if sensor_name == "":
        return sensor_name
    domain_names = {
        "temperature": ("Temperature", ("temp", "temperature")),
        "temperaturef": ("Temperature", ("temp", "temperature")),
        "voltage": ("Voltage", ("volt", "voltage")),
        "current": ("Current", ("amp", "current")),
        "power": ("Power", ("watt", "power")),
        "fan": ("Fan", ("fan", "rpm")),
        "frequency": ("Frequency", ("frequency", "hz")),
    }
    domain_name, domain_tokens = domain_names.get(str(sdr_class), ("", ()))
    lower_name = sensor_name.lower()
    if domain_name != "" and not any(token in lower_name for token in domain_tokens):
        return f"{sensor_name} {domain_name}"
    return sensor_name


def sensor_icon_for_class(sdr_class):
    icons = {
        "temperature": "mdi:thermometer",
        "temperaturef": "mdi:thermometer",
        "voltage": "mdi:sine-wave",
        "current": "mdi:current-ac",
        "power": "mdi:flash",
        "fan": "mdi:fan",
        "frequency": "mdi:sine-wave",
    }
    return icons.get(str(sdr_class), "")


def sensor_payload_for_class(device_mqtt_config, sdr_name, unique_id, sdr_class, state_topic):
    payload = {
        "device": device_mqtt_config,
        "name": sdr_name,
        "unique_id": unique_id,
        "force_update": True,
        "retain": True,
        "state_topic": state_topic,
    }
    icon = sensor_icon_for_class(sdr_class)
    if icon != "":
        payload["icon"] = icon
    if sdr_class == "temperature":
        payload["device_class"] = "temperature"
        payload["unit_of_meas"] = "°C"
        payload["state_class"] = "measurement"
    elif sdr_class == "temperaturef":
        payload["device_class"] = "temperature"
        payload["unit_of_meas"] = "°F"
        payload["state_class"] = "measurement"
    elif sdr_class == "voltage":
        payload["device_class"] = "voltage"
        payload["unit_of_meas"] = "V"
        payload["state_class"] = "measurement"
    elif sdr_class == "current":
        payload["device_class"] = "current"
        payload["unit_of_meas"] = "A"
        payload["state_class"] = "measurement"
    elif sdr_class == "power":
        payload["device_class"] = "power"
        payload["unit_of_meas"] = "W"
        payload["state_class"] = "measurement"
    elif sdr_class == "fan":
        payload["unit_of_meas"] = "RPM"
    elif sdr_class == "frequency":
        payload["device_class"] = "frequency"
        payload["unit_of_meas"] = "Hz"
        payload["state_class"] = "measurement"
    return payload


def parse_ipmi_sdr_row(server_sdr_state):
    server_sdr_values = server_sdr_state.split("|")
    if len(server_sdr_values) < 5:
        return None
    return {
        "SUBCLASS": server_sdr_values[0].strip(),
        "STATUS": server_sdr_values[2].strip(),
        "VALUE": server_sdr_values[3].strip(),
        "READING": server_sdr_values[4].strip(),
    }


def classify_sdr_reading(sensor_reading):
    sensor_reading = sensor_reading.lower()
    if "degrees c" in sensor_reading:
        return "temperature"
    if "degrees f" in sensor_reading:
        return "temperaturef"
    if "rpm" in sensor_reading:
        return "fan"
    if "amps" in sensor_reading:
        return "current"
    if "volts" in sensor_reading:
        return "voltage"
    if "watts" in sensor_reading:
        return "power"
    if "hz" in sensor_reading:
        return "frequency"
    return ""


def numeric_sdr_value(sensor_reading):
    sensor_reading = sensor_reading.strip()
    if sensor_reading in ("", "Disabled", "No Reading"):
        return ""
    numeric_match = re.search(r'-?\d+(?:\.\d+)?', sensor_reading)
    if numeric_match:
        return numeric_match.group(0)
    return ""


def dell_sdrs_from_elist(server_sdr_state):
    sdr_rows = []
    topic_counts = {}
    for server_sdr_line in server_sdr_state.splitlines():
        sdr_row = parse_ipmi_sdr_row(server_sdr_line)
        if sdr_row is None:
            continue
        sdr_class = classify_sdr_reading(sdr_row["READING"])
        if sdr_row["STATUS"] != "ok" or sdr_class == "" or numeric_sdr_value(sdr_row["READING"]) == "":
            continue
        sdr_row["SDR_CLASS"] = sdr_class
        sdr_row["SDR_TOPIC"] = sdr_row["SUBCLASS"]
        topic_counts[sdr_row["SDR_TOPIC"]] = topic_counts.get(sdr_row["SDR_TOPIC"], 0) + 1
        sdr_rows.append(sdr_row)
    sdrs = []
    for sdr_row in sdr_rows:
        sdr_topic = sdr_row["SDR_TOPIC"]
        if topic_counts[sdr_topic] > 1:
            sdr_topic = f"{sdr_row['SUBCLASS']} {sdr_row['VALUE']}"
        sdrs.append({
            "SDR_TYPE": sdr_topic,
            "SDR_TOPIC": sdr_topic,
            "SDR_NAME": sdr_display_name(sdr_topic, sdr_row["SDR_CLASS"]),
            "SDR_CLASS": sdr_row["SDR_CLASS"],
            "SUBCLASS": sdr_row["SUBCLASS"],
            "VALUE": sdr_row["VALUE"],
        })
    return sdrs


def get_sdr_topic(current_sdr, sdr_topic_types):
    if 'SDR_TOPIC' in current_sdr:
        return mqtt_path_segment(current_sdr['SDR_TOPIC'])
    if 'SDR_TYPE' in current_sdr:
        sdr_type = current_sdr['SDR_TYPE']
        if sdr_type in sdr_topic_types:
            return mqtt_path_segment(sdr_topic_types[sdr_type])
        try:
            int_sdr_type = int(sdr_type)
            if int_sdr_type in sdr_topic_types:
                return mqtt_path_segment(sdr_topic_types[int_sdr_type])
        except Exception:
            pass
    if 'SUBCLASS' in current_sdr:
        return mqtt_path_segment(current_sdr['SUBCLASS'])
    return mqtt_path_segment(current_sdr['VALUE'])


def dell_matching_row(current_sdr, server_sdr_state):
    sdr_subclass = current_sdr['SUBCLASS']
    sdr_entity = str(current_sdr.get('VALUE', '')).strip()
    server_sdr_values = server_sdr_state.split("\n")
    server_sdr_values = list(filter(lambda x: x.split("|")[0].strip() == sdr_subclass if "|" in x else False, server_sdr_values))
    if sdr_entity != "":
        server_sdr_values = list(filter(lambda x: len(x.split("|")) > 3 and x.split("|")[3].strip() == sdr_entity, server_sdr_values))
    if len(server_sdr_values) == 0:
        logging.warning(f"The DELL SDR subclass {sdr_subclass} was not found in the IPMI output.")
        return None
    return server_sdr_values[0].split("|")


class PyghmiBackend:
    """Persistent pyghmi backend keyed by BMC address."""

    def __init__(self, command_factory=None):
        self.command_factory = command_factory
        self.sessions = {}

    def session_for(self, server):
        server_ip = str(server['IPMI_IP'])
        session = self.sessions.get(server_ip)
        if session is None:
            session = PyghmiSession(server, self.command_factory)
            self.sessions[server_ip] = session
        return session

    def reconnect(self, server):
        server_ip = str(server['IPMI_IP'])
        self.sessions[server_ip] = PyghmiSession(server, self.command_factory)
        return self.sessions[server_ip]


class PyghmiSession:
    def __init__(self, server, command_factory=None):
        self.server = server
        if command_factory is None:
            from pyghmi.ipmi.command import Command
            command_factory = Command
        self.command = command_factory(
            bmc=str(server['IPMI_IP']),
            userid=str(server['IPMI_USER']),
            password=str(server['IPMI_PASSWORD']),
            keepalive=True,
        )

    def guid(self):
        response = self.command.raw_command(netfn=0x06, command=0x37)
        data = bytes(response.get('data', b''))
        if data == b'':
            return ''
        return data.hex()

    def power_state(self):
        return str(self.command.get_power().get('powerstate', ''))

    def set_power(self, powerstate):
        return self.command.set_power(powerstate)

    def sensor_readings(self):
        return list(self.command.get_sensor_data())

    def targeted_sensor_readings(self, names):
        names = {str(name).strip() for name in names if str(name).strip() != ""}
        if not names:
            return []
        sdr = self.command.init_sdr()
        readings = []
        for sensor in sdr.sensors.values():
            if str(getattr(sensor, 'name', '') or '').strip() not in names:
                continue
            response = self.command.raw_command(
                command=0x2d,
                netfn=4,
                rslun=sensor.sensor_lun,
                data=(sensor.sensor_number,),
            )
            if 'error' in response:
                continue
            readings.append(sensor.decode_sensor_reading(self.command, response['data']))
        return readings


def classify_pyghmi_sensor(reading):
    units = str(getattr(reading, 'units', '') or '').strip().lower()
    name = str(getattr(reading, 'name', '') or '').strip().lower()
    if units in ('°c', 'c') or 'degrees c' in units:
        return 'temperature'
    if units in ('°f', 'f') or 'degrees f' in units:
        return 'temperaturef'
    if units == 'v':
        return 'voltage'
    if units == 'a':
        return 'current'
    if units == 'w':
        return 'power'
    if units == 'rpm':
        return 'fan'
    if units == 'hz':
        return 'frequency'
    if 'temp' in name:
        return 'temperature'
    if 'fan' in name and 'rpm' in name:
        return 'fan'
    if 'current' in name:
        return 'current'
    if 'voltage' in name:
        return 'voltage'
    if 'power' in name or 'system level' in name:
        return 'power'
    return ''


def pyghmi_value(reading):
    value = getattr(reading, 'value', None)
    if value is None or getattr(reading, 'unavailable', 0):
        return ''
    return str(value)


def sensor_matches_config(reading, current_sdr):
    reading_name = str(getattr(reading, 'name', '') or '').strip()
    configured_name = str(current_sdr.get('SUBCLASS', current_sdr.get('SDR_TOPIC', ''))).strip()
    if configured_name == '':
        return False
    if reading_name == configured_name:
        return True
    return mqtt_safe_identifier(reading_name) == mqtt_safe_identifier(configured_name)


def pyghmi_readings_to_sdrs(readings):
    visible = []
    topic_counts = {}
    for reading in readings:
        sdr_class = classify_pyghmi_sensor(reading)
        value = pyghmi_value(reading)
        name = str(getattr(reading, 'name', '') or '').strip()
        if name == '' or sdr_class == '' or value == '':
            continue
        topic_counts[name] = topic_counts.get(name, 0) + 1
        visible.append((reading, name, sdr_class, value))

    used_topics = {}
    sdrs = []
    for reading, name, sdr_class, value in visible:
        topic = name
        if topic_counts[name] > 1:
            topic = f"{name} {len([s for s in sdrs if s['SUBCLASS'] == name]) + 1}"
        topic_path = mqtt_path_segment(topic)
        if topic_path in used_topics:
            used_topics[topic_path] += 1
            topic = f"{topic} {used_topics[topic_path]}"
        else:
            used_topics[topic_path] = 1
        sdrs.append({
            "SDR_TYPE": topic,
            "SDR_TOPIC": topic,
            "SDR_NAME": sdr_display_name(topic, sdr_class),
            "SDR_CLASS": sdr_class,
            "SUBCLASS": name,
            "VALUE": value,
            "READING": reading,
        })
    return sdrs


class SensorUpdateEngine:
    def __init__(self, backend, fallback_interval=1):
        self.backend = backend
        self.fallback_interval = fallback_interval
        self.discovery_cache = {}
        self.value_cache = {}
        self.poll_count = {}

    def reset_server(self, server_identifier):
        self.discovery_cache.pop(server_identifier, None)
        keys = [key for key in self.value_cache if key[0] == server_identifier]
        for key in keys:
            self.value_cache.pop(key, None)
        self.poll_count.pop(server_identifier, None)

    def dell_snapshot(self, server, server_identifier, sdr_topic_types):
        session = self.backend.session_for(server)
        return self.dell_snapshot_from_readings(server, server_identifier, sdr_topic_types, session.sensor_readings())

    def high_priority_sdr_names(self, server):
        names = []
        for sdr in server.get('SDRS', []) or []:
            if sdr.get('HIGH_PRIORITY') or str(sdr.get('SDR_CLASS', '')).lower() == 'power':
                name = str(sdr.get('SUBCLASS', sdr.get('SDR_TOPIC', ''))).strip()
                if name != "":
                    names.append(name)
        return names

    def dell_target_snapshot(self, server, server_identifier, sdr_topic_types):
        names = self.high_priority_sdr_names(server)
        if not names:
            return []
        session = self.backend.session_for(server)
        if not hasattr(session, "targeted_sensor_readings"):
            return []
        return self.dell_snapshot_from_readings(server, server_identifier, sdr_topic_types, session.targeted_sensor_readings(names))

    def dell_target_changes(self, server, server_identifier, sdr_topic_types, force_discovery=False):
        readings = self.dell_target_snapshot(server, server_identifier, sdr_topic_types)
        current_topics = self.discovery_cache.get(server_identifier, set())
        changed = []
        for reading in readings:
            current_topics.add(reading["topic"])
            cache_key = (server_identifier, reading["topic"])
            previous_value = self.value_cache.get(cache_key)
            if previous_value != reading["value"] or force_discovery:
                changed.append(reading)
                self.value_cache[cache_key] = reading["value"]
        self.discovery_cache[server_identifier] = current_topics
        return changed, set()

    def dell_snapshot_from_readings(self, server, server_identifier, sdr_topic_types, raw_readings):
        if 'SDRS' in server and server['SDRS']:
            sdr_list = []
            unmatched = list(raw_readings)
            for current_sdr in server['SDRS']:
                match = next((reading for reading in unmatched if sensor_matches_config(reading, current_sdr)), None)
                if match is None:
                    logging.warning(f"The configured DELL SDR {current_sdr.get('SUBCLASS', current_sdr.get('SDR_TOPIC', ''))} was not found in pyghmi sensor data.")
                    continue
                if match in unmatched:
                    unmatched.remove(match)
                sdr = dict(current_sdr)
                sdr["READING"] = match
                sdr["VALUE"] = pyghmi_value(match)
                sdr.setdefault("SDR_CLASS", classify_pyghmi_sensor(match))
                if "SDR_TYPE" not in sdr:
                    sdr.setdefault("SDR_TOPIC", sdr.get("SUBCLASS", str(getattr(match, 'name', ''))))
                sdr.setdefault("SDR_NAME", sdr_display_name(sdr.get("SDR_TOPIC", sdr.get("SUBCLASS", sdr.get("SDR_TYPE", ""))), sdr["SDR_CLASS"]))
                sdr_list.append(sdr)
        else:
            sdr_list = pyghmi_readings_to_sdrs(raw_readings)

        readings = []
        for current_sdr in sdr_list:
            sdr_value = str(current_sdr.get("VALUE", ""))
            if sdr_value == "":
                continue
            sdr_type = get_sdr_topic(current_sdr, sdr_topic_types)
            readings.append({
                "server_identifier": server_identifier,
                "topic": sdr_type,
                "value": sdr_value,
                "name": str(current_sdr.get('SDR_NAME', current_sdr.get('SUBCLASS', sdr_type))),
                "class": str(current_sdr.get('SDR_CLASS', '')),
                "source": current_sdr,
            })
        return readings

    def dell_snapshot_from_output(self, server, server_identifier, sdr_topic_types, full_output):
        if 'SDRS' in server and server['SDRS']:
            sdr_list = server['SDRS']
        else:
            sdr_list = dell_sdrs_from_elist(full_output)
        readings = []
        for current_sdr in sdr_list:
            matching_row = dell_matching_row(current_sdr, full_output)
            if matching_row is None:
                continue
            sdr_value = numeric_sdr_value(matching_row[4])
            sdr_type = get_sdr_topic(current_sdr, sdr_topic_types)
            readings.append({
                "server_identifier": server_identifier,
                "topic": sdr_type,
                "value": sdr_value,
                "name": str(current_sdr.get('SDR_NAME', current_sdr.get('SUBCLASS', sdr_type))),
                "class": str(current_sdr.get('SDR_CLASS', '')),
                "source": current_sdr,
            })
        return readings

    def dell_changes(self, server, server_identifier, sdr_topic_types, force_discovery=False):
        readings = self.dell_snapshot(server, server_identifier, sdr_topic_types)
        return self.dell_changes_from_readings(server_identifier, readings, force_discovery)

    def dell_changes_from_output(self, server, server_identifier, sdr_topic_types, full_output, force_discovery=False):
        readings = self.dell_snapshot_from_output(server, server_identifier, sdr_topic_types, full_output)
        return self.dell_changes_from_readings(server_identifier, readings, force_discovery)

    def dell_changes_from_readings(self, server_identifier, readings, force_discovery=False):
        current_topics = {reading["topic"] for reading in readings}
        previous_topics = self.discovery_cache.get(server_identifier, set())
        stale_topics = previous_topics - current_topics
        self.discovery_cache[server_identifier] = current_topics

        self.poll_count[server_identifier] = self.poll_count.get(server_identifier, 0) + 1
        should_emit_health = self.poll_count[server_identifier] % max(int(self.fallback_interval), 1) == 0

        changed = []
        for reading in readings:
            cache_key = (server_identifier, reading["topic"])
            previous_value = self.value_cache.get(cache_key)
            if previous_value != reading["value"] or reading["topic"] not in previous_topics or force_discovery:
                changed.append(reading)
                self.value_cache[cache_key] = reading["value"]
            elif should_emit_health:
                logging.debug(f"Sensor {server_identifier}/{reading['topic']} unchanged during fallback poll.")
        for stale_topic in stale_topics:
            self.value_cache.pop((server_identifier, stale_topic), None)
        return changed, stale_topics


class FixedRateTimer:
    """Absolute-deadline timer that skips missed ticks instead of drifting."""

    def __init__(self, period, clock=None, sleeper=None):
        self.period = float(period)
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.origin = self.clock()
        self.last_deadline = self.origin
        self.tick = 0

    def next_deadline(self, now=None):
        if self.period <= 0:
            return self.clock() if now is None else now
        if now is None:
            now = self.clock()
        elapsed_periods = math.floor((now - self.origin) / self.period)
        self.tick = max(self.tick + 1, elapsed_periods + 1)
        self.last_deadline = self.origin + self.tick * self.period
        return self.last_deadline

    def delay_until_next(self, now=None):
        if self.period <= 0:
            return 0
        if now is None:
            now = self.clock()
        return max(0, self.next_deadline(now) - now)

    def sleep_until_next(self):
        delay = self.delay_until_next()
        if delay > 0:
            self.sleeper(delay)
        return delay

    def overrun(self, started_at, finished_at=None):
        if self.period <= 0:
            return 0
        if finished_at is None:
            finished_at = self.clock()
        return max(0, finished_at - started_at - self.period)


def advance_deadline(deadline, period, now):
    if period <= 0:
        return now
    while deadline <= now:
        deadline += period
    return deadline


class PollMetrics:
    def __init__(self):
        self.total_cycles = 0
        self.overruns = 0
        self.last_cycle_seconds = 0
        self.last_overrun_seconds = 0
        self.max_cycle_seconds = 0

    def record(self, cycle_seconds, overrun_seconds):
        self.total_cycles += 1
        self.last_cycle_seconds = cycle_seconds
        self.last_overrun_seconds = overrun_seconds
        self.max_cycle_seconds = max(self.max_cycle_seconds, cycle_seconds)
        if overrun_seconds > 0:
            self.overruns += 1

    def as_payload(self):
        return {
            "poll_cycles": self.total_cycles,
            "poll_overruns": self.overruns,
            "poll_last_cycle_seconds": f"{self.last_cycle_seconds:.3f}",
            "poll_last_overrun_seconds": f"{self.last_overrun_seconds:.3f}",
            "poll_max_cycle_seconds": f"{self.max_cycle_seconds:.3f}",
        }
