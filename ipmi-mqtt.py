#!/bin/python 
# Las dependencias:
import yaml
import json
import socket
import argparse
import paho.mqtt.client as mqtt
import time
import os
import sys
import daemon
import logging
import logging.handlers as handlers
import re
import ipmi_mqtt_core as core

dell_discovery_cache = {}
sensor_update_engine = core.SensorUpdateEngine(core.PyghmiBackend())
poll_metrics = core.PollMetrics()
# First we define all the functions
# YAML config loading function
def load_config():
    try:
        config_dir = os.path.dirname(os.path.realpath(__file__))
        config_file = os.path.join(config_dir,'config', 'config.yaml')
        configuration = open(config_file, 'r')
        logging.info(f'Opening the following file: {config_file}')
        config = yaml.safe_load(configuration)
        return config, configuration
    except Exception as exception:
        logging.critical(f"There's an error accessing your config.yml file, the error is the following: {exception}")
        print("There's no config yaml file in the program's folder, please check the logs.")
        sys.exit()
# Connect to MQTT funcionts - this I took directly from the paho docs.
def on_connect(client, userdata, flags, rc):
    if int(rc) == 0:
        logging.debug(f"Succesfully connected to the MQTT broker. The rc is {rc}.")
        client.subscribe("$SYS/#")
        client.connected_flag=True #set flag for logic to wait for connection.
    elif int(rc) == 1:
        logging.info(f"The connection to the MQTT broker was refused due to an incorrect protocol version.The rc is {rc}.")
        print(f"The connection to the MQTT broker was refused due to an incorrect protocol version. The rc is {rc}.") 
    elif int(rc) == 2:
        logging.info(f"The connection to the MQTT broker was refused due to an incorrect client identifier. The rc is {rc}.") 
        print(f"The connection was refused due to an incorrect client identifier. The rc is {rc}.") 
    elif int(rc) == 3:
        logging.info(f"The connection to the MQTT broker was refused, the server is unavailable or there is mistake in the IP address.The rc is {rc}.") 
        print(f"The connection was refused, the server is unavailable or there is mistake in the IP address.The rc is {rc}.") 
    elif int(rc) == 4:
        logging.info(f"The connection to the MQTT broker was refused due to lack of authorization (wrong user or password).The rc is {rc}.")  
        print(f"The connection was refused due to lack of authorization (wrong user or password). The rc is {rc}.")  
    elif int(rc) == 5:
        logging.info(f"The connection to the MQTT broker was refused due to lack of authorization (wrong user or password).The rc is {rc}.")  
        print(f"The connection was refused due to lack of authorization (wrong user or password). The rc is {rc}.")  
def on_message(client, userdata, msg):
    if "$SYS/" in msg.topic: # I filter out the $SYS internal mqtt topic
        pass
    else:
        logging.info("You have the following message:"+ msg.topic+" "+str(msg.payload.decode("utf-8")))
        if str(msg.payload.decode("utf-8")) == "on":
            topic_parts = msg.topic.split("/")
            server_guid = topic_parts[-3]
            server_dict = complete_guid_dict[server_guid]
            sensor_update_engine.backend.session_for(server_dict).set_power("on")
            clean_topic_dict = {msg.topic: ""}
            mqtt_publish_dict(clean_topic_dict, client, mqtt_ip)
            get_single_power_data(complete_guid_dict, server_guid, topic_dict, ha_binary_topic, power_topic, client, mqtt_ip)
        elif str(msg.payload.decode("utf-8")) == "off":
            topic_parts = msg.topic.split("/")
            server_guid = topic_parts[-3]
            server_dict = complete_guid_dict[server_guid]
            sensor_update_engine.backend.session_for(server_dict).set_power("off")
            clean_topic_dict = {msg.topic: ""}
            mqtt_publish_dict(clean_topic_dict, client, mqtt_ip)
            get_single_power_data(complete_guid_dict, server_guid, topic_dict, ha_binary_topic, power_topic, client, mqtt_ip)
        pass
def on_publish(client, userdata, mid):
    logging.debug("the published message status:" + str(int(userdata or 0)) + " (0 means published)")
    logging.debug("the published message id is:" + str(mid))
def switch_subscribe(topic_dict, server_config, guid_dict, ha_switch_topic, switch_topic, client, mqtt_ip):
    try:
        if 'SWITCH' not in topic_dict or switch_topic == "":
            logging.info("You have no switch topic.")
        else:
            for server in server_config:
                server_nodename = server['IPMI_NODENAME']
                server_ip = str(server['IPMI_IP'])
                server_identifier = str("".join([guid_dict[server_ip]]))
                if server_identifier == "":
                    logging.warning(f"Can't subscribe to switch state changes for {server_nodename}, it has been skipped because no GUID was generated.")
                else:
                    server_mqtt_topic_subscribe = str(ha_switch_topic) + "/" + str(server_identifier) + "/" + mqtt_path_segment(switch_topic) + "/set"
                    client.subscribe(str(server_mqtt_topic_subscribe),2)
                    logging.info(f"You are now subscribed to {server_mqtt_topic_subscribe}.")
    except Exception as exception:
        logging.error(f"There is an error in your power sensor collection. The error is the following: {exception}")
def on_subscribe(client, userdata, mid, granted_qos):
    logging.info(f"The server has acknowledged your subscription requested on mid {mid} with qos {granted_qos}")
def mqtt_safe_identifier(identifier):
    return core.mqtt_safe_identifier(identifier)
def mqtt_path_segment(identifier):
    return core.mqtt_path_segment(identifier)
def ha_unique_id(*parts):
    return core.ha_unique_id(*parts)
def mqtt_display_name(value):
    return core.mqtt_display_name(value)
def power_display_name(power_topic):
    return core.power_display_name(power_topic)
def sdr_display_name(sensor_name, sdr_class):
    return core.sdr_display_name(sensor_name, sdr_class)
def sensor_icon_for_class(sdr_class):
    return core.sensor_icon_for_class(sdr_class)
def sensor_payload_for_class(device_mqtt_config, sdr_name, unique_id, sdr_class, state_topic):
    return core.sensor_payload_for_class(device_mqtt_config, sdr_name, unique_id, sdr_class, state_topic)
def mqtt_publish_dict(mqtt_dict, client, mqtt_ip):
    for x, y in mqtt_dict.items():
        publish_result = client.publish(str(x), str(y), qos=2, retain=True)
        if hasattr(publish_result, "wait_for_publish"):
            try:
                publish_result.wait_for_publish()
            except RuntimeError as exception:
                logging.warning(f"MQTT publish to {x} did not complete cleanly: {exception}")
        logging.debug("You have sent the following payload: " + str(y))
        logging.debug("To the following topic: " + str(x))
        logging.debug("On the server with IP: " + mqtt_ip)
def publish_poll_metrics(ha_sensor_topic, client, mqtt_ip):
    metric_payload = {}
    for metric_name, value in poll_metrics.as_payload().items():
        metric_payload[f"{ha_sensor_topic}/ipmi_mqtt/{metric_name}/state"] = value
    mqtt_publish_dict(metric_payload, client, mqtt_ip)
def get_mqtt(config):
    try:
        mqtt_dict = config['MQTT']
        mqtt_ip = mqtt_dict['MQTT_ip']
        mqtt_user = mqtt_dict['MQTT_USER']
        mqtt_pass = mqtt_dict['MQTT_PW']
        mqtt_client_id = mqtt_dict.get('MQTT_ID', 'ipmi-mqtt')
        if str(mqtt_client_id) in ("", "ipmi-mqtt-server"):
            mqtt_client_id = f"ipmi-mqtt-{socket.gethostname()}-{os.getpid()}"
        period = float(mqtt_dict['TIME_PERIOD'])
        logging.debug("This is your mqtt dictionary:" + str(mqtt_dict))
        if 'HA_BINARY' in mqtt_dict:
            ha_binary_topic= mqtt_dict['HA_BINARY']
        else:
            logging.warning('There is no binary topic in your YAML file.')
        if 'HA_SENSOR' in mqtt_dict:
            ha_sensor_topic= mqtt_dict['HA_SENSOR']
        else:
            logging.warning('There is no sensor topic in your YAML file.')
        if 'HA_SWITCH' in mqtt_dict:
            ha_switch_topic= mqtt_dict['HA_SWITCH']
        else:
            ha_switch_topic= ""
            logging.warning('There is no switch topic in your YAML file.')
    except Exception as exception:
        logging.critical(f'Your YAML is missing something in the MQTT section. You get the following error: {exception} ')
    return mqtt_ip, mqtt_user, mqtt_pass, period, ha_binary_topic, ha_sensor_topic, ha_switch_topic, mqtt_client_id
def get_high_priority_period(config, period):
    mqtt_dict = config.get('MQTT') or {}
    configured_period = mqtt_dict.get('HIGH_PRIORITY_TIME_PERIOD', '')
    if configured_period == "":
        return period
    return float(configured_period)
def get_guid(server_config):
    try:
        guid_dict = {}
        complete_guid_dict =  {}
        for server in server_config:
            server_nodename = server['IPMI_NODENAME']
            server_identifier = mqtt_safe_identifier(server_nodename)
            server_ip = server['IPMI_IP']
            server_user = server['IPMI_USER']
            server_pass = server['IPMI_PASSWORD']
            ipmi_guid_pure = sensor_update_engine.backend.session_for(server).guid()
            if ipmi_guid_pure == '':
                logging.error(f"The server {server_nodename} has returned no GUID when connected through IPMI. There probably is a connection error.")
            guid_dict[server_ip]=server_identifier
            complete_guid_dict[server_identifier]={
                "server_ip": server_ip,
                "server_user": server_user,
                "server_pass": server_pass,
                "server_nodename": server_nodename,
                "IPMI_IP": server_ip,
                "IPMI_USER": server_user,
                "IPMI_PASSWORD": server_pass,
            } # I create a dictionnary with the server's identifier as the key for the whole server info
        logging.debug("The following server identifiers have been generated:" + str(guid_dict))

        return guid_dict, complete_guid_dict
    except Exception as exception:
        logging.critical(f"There is an error generating your server's guid. The error is the following: {exception}")
def get_topics(config):
    try:
        topic_dict = config.get('TOPICS') or {}
        if 'POWER' in topic_dict: 
            power_topic = topic_dict['POWER']
            logging.debug("This is your power topic:" + str(power_topic))
        else:
            power_topic = "server_power_state"
            logging.warning('There is no power topic in your YAML file, using server_power_state.')
        if 'SWITCH' in topic_dict: 
            switch_topic = topic_dict['SWITCH']
            logging.debug("This is your switch topic:" + str(switch_topic))
        else:
            switch_topic = ""
            logging.warning('There is no switch topic in your YAML file.')
        if 'SDR_TYPES' in topic_dict:
            sdr_topic_types = topic_dict['SDR_TYPES']
            sdr_count = len(sdr_topic_types)
            logging.debug("This are your SDR topics:" + str(sdr_topic_types))
        else:
            logging.warning('There are no SDR topics in your YAML file.')
            sdr_topic_types = {}
            sdr_count = 0
    except Exception as exception:
        logging.critical(f'Your YAML is missing something in the TOPICS section. You get the following error: {exception} ')
    logging.info(f'You have {sdr_count} SDRs in your YAML file.')           
    return topic_dict, power_topic, switch_topic, sdr_topic_types, sdr_count
def get_sdr_topic(current_sdr, sdr_topic_types):
    return core.get_sdr_topic(current_sdr, sdr_topic_types)
def parse_ipmi_sdr_row(server_sdr_state):
    return core.parse_ipmi_sdr_row(server_sdr_state)
def classify_sdr_reading(sensor_reading):
    return core.classify_sdr_reading(sensor_reading)
def dell_sdrs_from_elist(server_sdr_state):
    return core.dell_sdrs_from_elist(server_sdr_state)
def get_dell_elist_full(server):
    readings = sensor_update_engine.backend.session_for(server).sensor_readings()
    rows = []
    for sdr in core.pyghmi_readings_to_sdrs(readings):
        rows.append(f"{sdr['SUBCLASS']} | | ok | {sdr['VALUE']} | {sdr['VALUE']} {getattr(sdr['READING'], 'units', '')}")
    return "\n".join(rows)
def discover_dell_sdrs(server):
    return dell_sdrs_from_elist(get_dell_elist_full(server))
def get_server_sdrs(server):
    if 'SDRS' in server and server['SDRS']:
        return server['SDRS']
    if server['BRAND'] == 'DELL':
        return discover_dell_sdrs(server)
    return []
def dell_matching_row(current_sdr, server_sdr_state):
    return core.dell_matching_row(current_sdr, server_sdr_state)
def power_sdr_initialization(server_config, guid_dict, ha_binary_topic, power_topic, client, mqtt_ip):
    try:    
        if power_topic == "":
            logging.info("Power state discovery is disabled because no POWER topic is configured.")
            return
        power_payload = {}
        for server in server_config:
            server_nodename = server['IPMI_NODENAME']
            server_ip = server['IPMI_IP']
            server_identifier = str("".join([guid_dict[server_ip]]))
            if server_identifier == '':
                logging.warning(f"Power initialization for {server_nodename} has been skipped because no GUID was generated.")
            else:
                power_path = mqtt_path_segment(power_topic)
                device_mqtt_config = {"identifiers" : server_identifier, "configuration_url" : "http://" + server['IPMI_IP'], "manufacturer" : server['BRAND'], "name" : server_nodename}
                server_mqtt_config_topic = ha_binary_topic + "/" + server_identifier + "/" + power_path + "/" + "config"
                server_mqtt_state_topic = ha_binary_topic + "/" + server_identifier + "/" + power_path + "/" + "state"
                mqtt_payload = {"device" : device_mqtt_config, "device_class" : "power", "name" : power_display_name(power_topic), "unique_id" : ha_unique_id(server_identifier, "power"), "force_update" : True, "payload_on" : "on", "payload_off" : "off" , "retain" : True, "state_topic" : server_mqtt_state_topic }
                mqtt_payload = json.dumps(mqtt_payload)  
                power_payload[server_mqtt_config_topic] = mqtt_payload
                mqtt_publish_dict(power_payload, client, mqtt_ip)
    except Exception as exception:
        logging.critical(f"There was an error sending your device configuration.The error is: {exception}")
def switch_sdr_initialization(server_config, guid_dict, ha_switch_topic, switch_topic, ha_binary_topic, power_topic, client, mqtt_ip):
    try:    
        if switch_topic == "":
            logging.info("Switch discovery is disabled because no SWITCH topic is configured.")
            return
        switch_payload = {}
        for server in server_config:
            server_nodename = server['IPMI_NODENAME']
            server_ip = server['IPMI_IP']
            server_identifier = str("".join([guid_dict[server_ip]]))
            if server_identifier == '':
                logging.warning(f"Server Switch initialization for {server_nodename} has been skipped because no GUID was generated.")
            else:
                switch_path = mqtt_path_segment(switch_topic)
                power_path = mqtt_path_segment(power_topic)
                device_mqtt_config = {"identifiers" : server_identifier, "configuration_url" : "http://" + server['IPMI_IP'], "manufacturer" : server['BRAND'], "name" : server_nodename}
                server_mqtt_config_topic = ha_switch_topic + "/" + server_identifier + "/" + switch_path + "/" + "config"
                server_mqtt_state_topic = ha_binary_topic + "/" + server_identifier + "/" + power_path + "/" + "state"
                server_mqtt_command_topic = ha_switch_topic + "/" + server_identifier + "/" + switch_path + "/" + "set"
                # I add a power state to the switch, so that it's based on the power state topic previously created
                mqtt_payload = {"device" : device_mqtt_config, "device_class" : "switch", "name" : switch_topic , "unique_id" : ha_unique_id(server_identifier, "switch"), "force_update" : True, "payload_on" : "on", "payload_off" : "off" , "retain" : True, "state_topic" : server_mqtt_state_topic, "command_topic": server_mqtt_command_topic, "optimistic": True }
                mqtt_payload = json.dumps(mqtt_payload)  
                switch_payload[server_mqtt_config_topic] = mqtt_payload
                mqtt_publish_dict(switch_payload, client, mqtt_ip)
    except Exception as exception:
        logging.critical(f"There was an error sending your device configuration.The error is: {exception}")
def sensor_sdr_initialization(server_config, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip):
    try:    
        for server in server_config:
            if server['BRAND'] == 'DELL':
                logging.info(f"DELL sensor discovery is handled during collection for {server['IPMI_NODENAME']}.")
                continue
            server_nodename = server['IPMI_NODENAME']
            server_ip = str(server['IPMI_IP'])
            server_identifier = str("".join([guid_dict[server_ip]]))
            if server_identifier == '':
                logging.warning(f"SDR initialization for {server_nodename} has been skipped because no GUID was generated.")
            else:
                server_identifier = str("".join([guid_dict[server_ip]]))
                sdr_list = get_server_sdrs(server)
                sdr_payload = {}       
                device_mqtt_config = {"identifiers" : server_identifier, "configuration_url" : "http://" + server['IPMI_IP'], "manufacturer" : server['BRAND'], "name" : server_nodename} 
                for current_sdr in sdr_list:
                    sdr_type = get_sdr_topic(current_sdr, sdr_topic_types)
                    sdr_name = str(current_sdr.get('SDR_NAME', current_sdr.get('SDR_TOPIC', current_sdr.get('SUBCLASS', sdr_type))))
                    sdr_class = str(current_sdr.get('SDR_CLASS'))
                    sdr_topic = sdr_type
                    unique_id = ha_unique_id(server_identifier, "sdr", sdr_type)
                    server_mqtt_config_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "config"
                    server_mqtt_state_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "state"
                    mqtt_payload = sensor_payload_for_class(device_mqtt_config, sdr_name, unique_id, sdr_class, server_mqtt_state_topic)
                    mqtt_payload = json.dumps(mqtt_payload)  
                    sdr_payload[server_mqtt_config_topic] =  mqtt_payload
                    mqtt_publish_dict(sdr_payload, client, mqtt_ip)
    except Exception as exception:
        logging.error(f"There is an error in your SDR sensor collection. The error is the following: {exception}")
def publish_dell_sensor_changes(server, server_identifier, changed_readings, stale_topics, ha_sensor_topic, client, mqtt_ip):
    server_nodename = str(server['IPMI_NODENAME'])
    device_mqtt_config = {"identifiers" : server_identifier, "configuration_url" : "http://" + server['IPMI_IP'], "manufacturer" : server['BRAND'], "name" : server_nodename}
    current_topics = {}
    all_topics = sensor_update_engine.discovery_cache.get(server_identifier, set())
    for sdr_topic in all_topics:
        server_mqtt_config_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "config"
        server_mqtt_state_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "state"
        current_topics[server_mqtt_config_topic] = server_mqtt_state_topic
    for reading in changed_readings:
        sdr_value = reading["value"]
        sdr_class = reading["class"]
        sdr_topic = reading["topic"]
        sdr_name = reading["name"]
        unique_id = ha_unique_id(server_identifier, "sdr", sdr_topic)
        server_mqtt_config_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "config"
        server_mqtt_state_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "state"
        sensor_payload = sensor_payload_for_class(device_mqtt_config, sdr_name, unique_id, sdr_class, server_mqtt_state_topic)
        mqtt_publish_dict({server_mqtt_state_topic: sdr_value}, client, mqtt_ip)
        mqtt_publish_dict({server_mqtt_config_topic: json.dumps(sensor_payload)}, client, mqtt_ip)
    previous_topics = dell_discovery_cache.get(server_identifier, {})
    stale_config_topics = {
        ha_sensor_topic + "/" + server_identifier + "/" + stale_topic + "/" + "config"
        for stale_topic in stale_topics
    }
    stale_config_topics.update(set(previous_topics.keys()) - set(current_topics.keys()))
    for stale_config_topic in stale_config_topics:
        stale_state_topic = previous_topics.get(stale_config_topic, "")
        if stale_state_topic == "":
            stale_state_topic = stale_config_topic[:-len("/config")] + "/state"
        mqtt_publish_dict({stale_config_topic: ""}, client, mqtt_ip)
        if stale_state_topic != "":
            mqtt_publish_dict({stale_state_topic: ""}, client, mqtt_ip)
    dell_discovery_cache[server_identifier] = current_topics
def publish_dell_sensor_cycle(server, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip):
    server_nodename = str(server['IPMI_NODENAME'])
    server_ip = str(server['IPMI_IP'])
    server_identifier = str("".join([guid_dict[server_ip]]))
    if server_identifier == "":
        logging.warning(f"DELL SDR sensor data collection for {server_nodename} has been skipped because no GUID was generated.")
        return
    if server_identifier not in dell_discovery_cache:
        sensor_update_engine.reset_server(server_identifier)
    changed_readings, stale_topics = sensor_update_engine.dell_changes(server, server_identifier, sdr_topic_types)
    publish_dell_sensor_changes(server, server_identifier, changed_readings, stale_topics, ha_sensor_topic, client, mqtt_ip)
def publish_dell_high_priority_cycle(server, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip):
    server_ip = str(server['IPMI_IP'])
    server_identifier = str("".join([guid_dict[server_ip]]))
    if server_identifier == "":
        return
    changed_readings, stale_topics = sensor_update_engine.dell_target_changes(server, server_identifier, sdr_topic_types)
    publish_dell_sensor_changes(server, server_identifier, changed_readings, stale_topics, ha_sensor_topic, client, mqtt_ip)
def get_power_data(topic_dict, server_config, guid_dict, ha_binary_topic, power_topic, client, mqtt_ip):
    try:
        if power_topic == "":
            logging.info("You have no power topic.")
        else:
            power_states = {} #I create a dictionary
            for server in server_config:
                server_nodename = server['IPMI_NODENAME']
                server_ip = str(server['IPMI_IP'])
                server_guid = str("".join([guid_dict[server_ip]]))
                if server_guid == "":
                    logging.warning(f"Power sensor data collection for {server_nodename} has been skipped because no GUID was generated.")
                else:
                    server_mqtt_topic = ha_binary_topic + "/" + server_guid + "/" + mqtt_path_segment(power_topic) + "/" + "state"
                    server_power_state = sensor_update_engine.backend.session_for(server).power_state()
                    power_states[server_guid] = server_power_state #I use the GUIDs as key with the server's power state as output
                    client.publish(server_mqtt_topic, server_power_state, qos=2, retain=True)
                    logging.debug("You have sent the following payload: " + str(server_power_state))
                    logging.debug("To the power state topic: " + str(server_mqtt_topic))
                    logging.debug("On the server with IP: " + mqtt_ip)
        logging.debug(str(power_states))
    except Exception as exception:
        logging.error(f"There is an error in your power sensor collection. The error is the following: {exception}")
def get_single_power_data(complete_guid_dict, server_guid, topic_dict, ha_binary_topic, power_topic, client, mqtt_ip):
    try:
        if power_topic == "":
            logging.info("You have no power topic.")
        elif server_guid == "":
                logging.warning(f"Power sensor data collection for {server_nodename} has been skipped because no GUID was generated.")
        else:
            server_dict = complete_guid_dict[server_guid]
            server_ip = server_dict["server_ip"]
            server_nodename = server_dict["server_nodename"]
            server_mqtt_topic = ha_binary_topic + "/" + server_guid + "/" + mqtt_path_segment(power_topic) + "/" + "state"
            server_power_state = sensor_update_engine.backend.session_for(server_dict).power_state()
            client.publish(server_mqtt_topic, server_power_state, qos=2, retain=True)
            logging.debug("You have sent the following payload: " + str(server_power_state))
            logging.debug("To the power state topic: " + str(server_mqtt_topic))
            logging.debug("On the server with IP: " + mqtt_ip)
    except Exception as exception:
        logging.error(f"There is an error in your power sensor collection. The error is the following: {exception}")
def supermicro_ipmi_format(current_sdr, server_sdr_state):
    try:
        server_sdr_values = server_sdr_state.split("|")
        if current_sdr['SDR_CLASS'] == 'temperature':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:3]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        elif current_sdr['SDR_CLASS'] == 'fan':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        elif current_sdr['SDR_CLASS'] == 'frequency':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
            sdr_value = int(sdr_value)/60
        elif current_sdr['SDR_CLASS'] == 'voltage':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        else:
            sdr_value = server_sdr_values[4]
            logging.info(f"The SDR class {current_sdr['SDR_CLASS']} is not defined so we're gonna take the complete information from the column.")
        return sdr_value
    except Exception as exception:
        logging.critical(f'There was a problem getting SDR sensor states, specifically when trying to apply the formatting for Supermicro servers. You get the following error: {exception} ')
def asus_ipmi_format(current_sdr, server_sdr_state):
    try:
        sdr_subclass = current_sdr['SUBCLASS']
        server_sdr_values = server_sdr_state.split("\n")
        server_sdr_values = list(filter(lambda x: x.startswith(sdr_subclass), server_sdr_values))
        server_sdr_values = server_sdr_values[0].split("|")
        if current_sdr['SDR_CLASS'] == 'temperature':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:3]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        elif current_sdr['SDR_CLASS'] == 'fan':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        elif current_sdr['SDR_CLASS'] == 'frequency':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
            sdr_value = int(sdr_value)/60
        elif current_sdr['SDR_CLASS'] == 'voltage':
            sdr_value = server_sdr_values[4]
            sdr_value = sdr_value[:6]
            sdr_value = sdr_value.strip()
            sdr_value = re.sub(r'[^0-9]', '', sdr_value)
        else:
            sdr_value = server_sdr_values[4]
            logging.info(f"The SDR class {current_sdr['SDR_CLASS']} is not defined so we're gonna take the complete information from the column.")
        return sdr_value
    except Exception as exception:
        logging.critical(f'There was a problem getting SDR sensor states, specifically when trying to apply the formatting for ASUS servers. You get the following error: {exception} ')
def numeric_sdr_value(sensor_reading):
    return core.numeric_sdr_value(sensor_reading)
def dell_ipmi_format(current_sdr, server_sdr_state):
    try:
        sdr_subclass = current_sdr['SUBCLASS']
        sdr_entity = str(current_sdr.get('VALUE', '')).strip()
        server_sdr_values = server_sdr_state.split("\n")
        server_sdr_values = list(filter(lambda x: x.split("|")[0].strip() == sdr_subclass if "|" in x else False, server_sdr_values))
        if sdr_entity != "":
            server_sdr_values = list(filter(lambda x: len(x.split("|")) > 3 and x.split("|")[3].strip() == sdr_entity, server_sdr_values))
        if len(server_sdr_values) == 0:
            logging.warning(f"The DELL SDR subclass {sdr_subclass} was not found in the IPMI output.")
            return ""
        server_sdr_values = server_sdr_values[0].split("|")
        sdr_value = numeric_sdr_value(server_sdr_values[4])
        if sdr_value == "":
            logging.warning(f"IPMI returned an empty value for DELL SDR subclass {sdr_subclass}.")
        return sdr_value
    except Exception as exception:
        logging.critical(f'There was a problem getting SDR sensor states, specifically when trying to apply the formatting for DELL servers. You get the following error: {exception} ')
def get_sdr_data(current_sdr, server_ip, server_user, server_pass, sdr_topic_types, server_nodename, server):
    try:
        for reading in sensor_update_engine.backend.session_for(server).sensor_readings():
            if core.sensor_matches_config(reading, current_sdr):
                return core.pyghmi_value(reading), get_sdr_topic(current_sdr, sdr_topic_types)
        logging.warning(f"The SDR {current_sdr.get('SUBCLASS', current_sdr.get('SDR_TOPIC', ''))} was not found in pyghmi sensor data for {server_nodename}.")
        return "", get_sdr_topic(current_sdr, sdr_topic_types)
    except Exception as exception:
        logging.critical(f'There was a problem getting SDR data. You get the following error: {exception} ')
def get_sdr_sensor_states(server_config, guid_dict, sdr_topic_types, ha_sensor_topic):
    try:
        sdr_states = {} #I create a dictionary for all the servers
        sdr_sensor_mqtt_dict = {}
        for server in server_config:

            server_nodename = str(server['IPMI_NODENAME'])
            server_ip = str(server['IPMI_IP'])
            server_identifier = str("".join([guid_dict[server_ip]]))
            if server_identifier == "":
                logging.warning(f"SDR sensor data collection for {server_nodename} has been skipped because no GUID was generated.")
            else:
                server_user = str(server['IPMI_USER'])
                server_pass = str(server['IPMI_PASSWORD'])
                if server['BRAND'] == 'DELL':
                    continue
                sdr_list = sensor_update_engine.dell_snapshot(server, server_identifier, sdr_topic_types)
                sdr_server_dict = {} # I create a dictionary with all of the servers values
                for current_sdr in sdr_list:
                    sdr_type = current_sdr["topic"]
                    sdr_value = current_sdr["value"]
                    if sdr_value == '':
                        logging.warning(f" Server {server_nodename} has returned no SDR information over IPMI, a connection problem is likely.")
                    else:
                        sdr_topic = sdr_type
                        sdr_server_dict[sdr_type] = sdr_value
                        server_mqtt_state_topic = ha_sensor_topic + "/" + server_identifier + "/" + sdr_topic + "/" + "state"
                        sdr_sensor_mqtt_dict[server_mqtt_state_topic] = sdr_value
                    sdr_states[server_identifier] = sdr_server_dict
        return sdr_sensor_mqtt_dict, sdr_states
    except Exception as exception:
        logging.critical(f'There was a problem getting SDR sensor states. You get the following error: {exception} ')
def main(): # Here i have the main program
    """Main function to run ipmi-mqtt in a loop."""
    try:
        #Here I load yaml configuration files and create variables for the elements in the yaml
            global config, configuration, server_config
            config, configuration = load_config()
            try:
                server_config = config['SERVERS']
                if server_config is None:
                    logging.warning("You have no servers.")  
                else:
                    server_count = len(server_config)
                    logging.info(f"You have {server_count} servers.")
                    logging.debug(f"This is the configuration information they have: {str(server_config)}")
            except Exception as exception:
                logging.critical(f'Your YAML is missing something in the SERVERS section. You get the following error: {exception} ')
    except Exception as exception:
        logging.critical(f"Please check your YAML, it might be missing some parts. The exception is {exception}")
    #Create config variables
    global mqtt_ip, mqtt_user, mqtt_pass, period, guid_dict, complete_guid_dict, topic_dict, ha_binary_topic, power_topic, mqtt_client_id
    mqtt_ip, mqtt_user, mqtt_pass, period, ha_binary_topic, ha_sensor_topic, ha_switch_topic, mqtt_client_id = get_mqtt(config)
    high_priority_period = get_high_priority_period(config, period)
    #Get GUID for each server through IPMI and SERVER IP DICT for each server based on GUID
    guid_dict, complete_guid_dict=get_guid(server_config)
    logging.debug(f"This is the server information organized by GUID: {str(complete_guid_dict)}")
    #GET SERVER IP DICT for each server based on GUID
    topic_dict, power_topic, switch_topic, sdr_topic_types, sdr_count = get_topics(config)
    #I first copy methods according to Paho MQTT documentation, then I set the mqtt user and password (which is why I needed first the get_mqtt method, then I start the connection and finally I create the network loop.)
    try:
        mqtt.Client.connected_flag=False#create flag in class
        client = mqtt.Client(str(mqtt_client_id), False)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_publish = on_publish
        client.on_subscribe = on_subscribe
        client.username_pw_set(mqtt_user, password=mqtt_pass)
        client.loop_start()
        client.connect(mqtt_ip, 1883, 60)
        while not client.connected_flag: #I wait in a loop until I receive a connection ack.
            logging.info("Connecting to MQTT Broker: waiting in loop until until the connection is established.")
            time.sleep(1)
        logging.info(f"Returning to the main loop, succesfully connected to the broker on {mqtt_ip}, with id {mqtt_client_id} and user {mqtt_user}")
    except Exception as exception:
        logging.critical(f"There seems to be a problem connecting to the mqtt server. The exception is {exception}")
    logging.debug(f"You have {str(sdr_count)} SDRs.")
    #First run - power device initialization on HA
    power_sdr_initialization(server_config, guid_dict, ha_binary_topic, power_topic, client, mqtt_ip)
    #First run switch initialization
    switch_sdr_initialization(server_config, guid_dict, ha_switch_topic, switch_topic, ha_binary_topic, power_topic, client, mqtt_ip)
    # First run Sensor initialization
    sensor_sdr_initialization(server_config, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip)
    logging.info("Initialization complete.")
    if getattr(args,'i'):
        logging.info("Started in iniatilization mode, so stopping now.")
        client.disconnect
        client.loop_stop()
        quit()
    else:
        #I subscribe for switch topics on the mqtt broker
        if switch_topic != "":
            switch_subscribe(topic_dict, server_config, guid_dict, ha_switch_topic, switch_topic, client, mqtt_ip)
            logging.info(f"Subscribing to switch topic.")
        else:
            logging.info("There is no switch topic to subscribe to.")
            pass
        #And now I run th main loop that will check for ipmi states and publish them
        loop_periods = [value for value in (period, high_priority_period) if value > 0]
        loop_period = min(loop_periods) if loop_periods else 0
        full_next_at = time.monotonic()
        high_priority_next_at = full_next_at
        while(True):
            cycle_started_at = time.monotonic()
            now = cycle_started_at
            run_full = period == 0 or now >= full_next_at
            run_high_priority = high_priority_period > 0 and now >= high_priority_next_at
            if run_full:
                #Sensor data gathering
                # I get the power data from each server, one by one (following guid_dict order) and then send that data through mqtt to the mqtt server
                get_power_data(topic_dict, server_config, guid_dict, ha_binary_topic, power_topic, client, mqtt_ip)
                for server in server_config:
                    if server['BRAND'] == 'DELL':
                        publish_dell_sensor_cycle(server, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip)
                # Get SDR DATA for each server if configured, or discovered for supported platforms.
                try:
                    sdr_sensor_mqtt_dict, sdr_states = get_sdr_sensor_states(server_config, guid_dict, sdr_topic_types, ha_sensor_topic)
                    logging.debug("This is the dictionnary you are sending to publish: " + str(sdr_sensor_mqtt_dict))
                    mqtt_publish_dict(sdr_sensor_mqtt_dict, client, mqtt_ip)
                    logging.debug("These are the SDR States collected:" + str(sdr_states))
                except Exception as exception:
                    logging.error(f"There is an error in your SDR sensor collection. The error is the following: {exception}")
                full_next_at = core.advance_deadline(full_next_at, period, time.monotonic())
                high_priority_next_at = core.advance_deadline(high_priority_next_at, high_priority_period, time.monotonic())
            elif run_high_priority:
                for server in server_config:
                    if server['BRAND'] == 'DELL':
                        publish_dell_high_priority_cycle(server, guid_dict, sdr_topic_types, ha_sensor_topic, client, mqtt_ip)
                high_priority_next_at = core.advance_deadline(high_priority_next_at, high_priority_period, time.monotonic())
            if period == 0:  #If period set to 0, the script ends.
                logging.info("The time period in the YAML file is set to 0, so the script will end.")
                client.disconnect
                client.loop_stop()
                quit()
            elif getattr(args,'o'):
                logging.info("Started in run once mode, so stopping now.")
                client.disconnect
                client.loop_stop()
                quit()
            else:
                cycle_finished_at = time.monotonic()
                active_period = period if run_full else high_priority_period
                overrun = max(0, cycle_finished_at - cycle_started_at - active_period)
                poll_metrics.record(cycle_finished_at - cycle_started_at, overrun)
                publish_poll_metrics(ha_sensor_topic, client, mqtt_ip)
                if overrun > 0:
                    logging.warning(f"Collection took {cycle_finished_at - cycle_started_at:.3f}s and overran the configured {active_period:.3f}s period by {overrun:.3f}s.")
                next_deadline = min(full_next_at, high_priority_next_at) if high_priority_period > 0 else full_next_at
                delay = max(0, next_deadline - time.monotonic())
                if delay > 0:
                    time.sleep(delay)
                logging.info(f"Collection complete, waited {delay:.3f} seconds for the next fixed-rate poll tick.")

#Some code that sets default parameters before running the program.
#We define some arguments to be parsed as well as help messages and description for the script.
parser = argparse.ArgumentParser(description='This is a simple python script that uses pyghmi in order to connect to your servers, review their power states and SDRs, if defined, and then send them through mqtt to an mqtt broker in order for Home Assistant to use them. In order for it to work, you must have filled your mqtt connetion information and your IPMI server connection information.')
parser.add_argument('-i', action='store_true', help='Run once to only create the entities in your MQTT broker (and see them in home assistant).')
parser.add_argument('-o', action='store_true', help='Run once and quit.')
parser.add_argument('-d', action='store_true', help='Run as a daemon.')
parser.add_argument('-s', action='store_true', help='Run only subscribe.')
parser.add_argument('-DEBUG', action='store_true', help='Add Debug messages to log.')
args = parser.parse_args()
#We define the logic and place where we're gonna log things
log_dir = os.path.dirname(os.path.realpath(__file__))  
log_fname = os.path.join(log_dir, 'config','ipmi-mqtt.log') #I define a relative path for the log to be saved on the same folder as my config file
formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")
logger = logging.getLogger() # I define format and instantiate first logger
fh = handlers.RotatingFileHandler(log_fname, mode='w', maxBytes=100000, backupCount=3) #This handler is important as I need a handler to pass to my daemon when run in daemon mode
fh.setFormatter(formatter) 
logger.addHandler(fh)
#And we define the attributes when running the program
if getattr(args,'DEBUG'):
    logger.setLevel(logging.DEBUG) 
    fh.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
if getattr(args,'i'):
    logging.info("Running with -i in initialization mode.")
if getattr(args,'o'):
    logging.info("Running with -o in run once mode.")
if getattr(args,'d'):
    logging.info("Running with -d in daemon mode.")
if getattr(args,'DEBUG'):
    logging.info("Running with -DEBUG in DEBUG log mode.")
if getattr(args,'d'):
    config, configuration = load_config()
    context = daemon.DaemonContext(files_preserve = [configuration, fh.stream] )
    with context:
        main()
elif getattr(args,'s'):
    logging.info("Running with -s in message subscribe mode (with no initialization).")
    global server_config
    config, configuration = load_config()
    server_config = config['SERVERS']
    global mqtt_ip, mqtt_user, mqtt_pass, period, guid_dict, complete_guid_dict, topic_dict, ha_binary_topic, power_topic, mqtt_client_id
    mqtt_ip, mqtt_user, mqtt_pass, period, ha_binary_topic, ha_sensor_topic, ha_switch_topic, mqtt_client_id = get_mqtt(config)
    topic_dict, power_topic, switch_topic, sdr_topic_types, sdr_count = get_topics(config)
    try:
        mqtt.Client.connected_flag=False#create flag in class
        client = mqtt.Client(str(mqtt_client_id), False)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_publish = on_publish
        client.on_subscribe = on_subscribe
        client.username_pw_set(mqtt_user, password=mqtt_pass)
        client.loop_start()
        client.connect(mqtt_ip, 1883, 60)
        while not client.connected_flag: #I wait in a loop until I receive a connection ack.
            logging.info("Connecting to MQTT Broker: waiting in loop until until the connection is established.")
            time.sleep(1)
        logging.info(f"Returning to the main loop, succesfully connected to the broker on {mqtt_ip}, with id {mqtt_client_id} and user {mqtt_user}")
    except Exception as exception:
        logging.critical(f"There seems to be a problem connecting to the mqtt server. The exception is {exception}")
    guid_dict, complete_guid_dict=get_guid(server_config)
    switch_subscribe(topic_dict, server_config, guid_dict, ha_switch_topic, switch_topic, client, mqtt_ip)
    while True:
        pass
elif __name__== '__main__':
        main()
