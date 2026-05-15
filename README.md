# ipmi-mqtt
Python app for IPMI states to be sent to Home Assistant via MQTT

## Provenance

This repository is maintained as a fork of the original `ipmi-mqtt` script with compatibility kept for the MQTT discovery and state topics used by existing Home Assistant installations. The current direction is to keep MQTT as a supported output while moving IPMI collection, sensor normalization, discovery diffing, and update emission into reusable core code that can also support future adapters.

This is a simple application that you can either run continuously in a predefined interval, run once (-o), use just to create your entities in home assistant through mqtt (-i) or run continuously as a daemon (-d). The script uses persistent pyghmi IPMI sessions to get IPMI sensor data from one or many servers and then republishes that data to MQTT in a format that Home Assistant automatically recognizes as devices, each with its own entities and switches so that the servers can be turned On or Off through IPMI.

If you want to use it as a service in linux or FreeBSD you can check the readme on the FreeBSD-service folder or the systemd-service folder in the repo and follow those instructions too. You can also run it with the container image published to GitHub Container Registry.

## Docker

The container image is published as:

```
ghcr.io/lukasmojzis/ipmi-mqtt:latest
```

Container builds publish branch tags and release tags. The `latest` tag is reserved for the default branch; pull request builds validate the image without pushing it.

Create your configuration file before starting the container:

```
cp "config/config - example.yaml" config/config.yaml
```

Edit `config/config.yaml`, then start it with Docker Compose:

```
docker compose up -d
```

Or run the image directly:

```
docker run --rm \
  -v "$PWD/config/config.yaml:/app/config/config.yaml:ro" \
  ghcr.io/lukasmojzis/ipmi-mqtt:latest
```

The container expects its configuration at `/app/config/config.yaml`.

The script requires:

python to be installed on the server 
for linux (apt):
```
sudo apt install python3 python3-pip
```
as well as the following modules with pip:

yaml, paho-mqtt, python-daemon, and pyghmi:
```
sudo pip install pyyaml paho-mqtt python-daemon pyghmi
```

for freebsd (pkg):

```
pkg install python3
```

as well as the following modules:

yaml, paho-mqtt, python-daemon, and pyghmi:
```
pkg install py39-daemon py39-yaml py39-paho-mqtt py39-pyghmi
```

Once installed, just copy this repo (you can use git clone), complete the YAML file and rename it config.yaml in the /config/ folder, make the script executable and run it.

That's it. You can execute it with -i in order to just execute the config payload being sent to the MQTT topic, or -d in order to have the script run as a daemon. You can also set a time (in seconds) inside the YAML file for the script to run in a loop and get new sensor values in that time period or simply run with -o to run one time only. 


All of the configuration is done via a config.yaml file, an example file is provided, you need to rename it to config.yaml.

It must contain:

An MQTT configuration with IP, user, password, the topics for sensors (the example ones are for HA to do discovery) and the time period, which is the amount of time before re-runs of the sensor data gathering, if set to 0 the script will not repeat itself (like with option -o), otherwise it will run until killed:
paho-mqtt:
```
MQTT:
    MQTT_ip: MQTT BROKER IP
    MQTT_USER: 'MQTT user'
    MQTT_PW: 'MQTTPASSWORD'
    HA_BINARY: 'homeassistant/binary_sensor'
    HA_SENSOR: 'homeassistant/sensor'
    HA_SWITCH: 'homeassistant/switch'
    TIME_PERIOD: 300

```

`TIME_PERIOD` accepts seconds and may be fractional. The poll loop uses fixed-rate deadlines, so it targets stable ticks instead of sleeping for `TIME_PERIOD` after each collection finishes. If a collection takes longer than the configured period, the next missed tick is skipped and the overrun is logged. This keeps the schedule predictable, but it cannot make IPMI return data faster than the BMC responds.

`HIGH_PRIORITY_TIME_PERIOD` is optional. When set, SDRs marked `HIGH_PRIORITY: true` and SDRs with `SDR_CLASS: power` are read on that faster cadence between full snapshots. Poll cycle duration, overrun count, and related poll metrics are also published to MQTT under the Home Assistant sensor topic. If `MQTT_ID` is omitted or left as the example `ipmi-mqtt-server`, the runtime client ID is made unique with the container hostname and process ID to avoid duplicate-client disconnects.


    
A topics configuration, which can have one POWER topic, an optional SWITCH topic and all of the SDRs (the name of the values that will be given to HA on the MQTT Broker), you must put one SDR type per type of SDR as you will reference them on the server configuration part. If `TOPICS` is omitted, read-only power state and supported sensor discovery are enabled; power control remains disabled unless `SWITCH` is explicitly configured.



```
TOPICS:
    POWER: 'THE NAME YOU WILL GIVE TO THE POWER TOPIC'
    #SWITCH: 'THE NAME YOU WILL GIVE TO THE SWITCH TOPIC'
    SDR_TYPES:
        1: 'server_cpu_temp'
        2: 'server_system_temp'
        3:  'server_cpu_fan'
        4:  'server_bmc_voltage'

```

On the SERVERS part, you can put as many servers as you wish  (I have 3), you must specify their nodename (the name you want to use for them), their brand (currently ASUS, SUPERMICRO or DELL), their IP, IPMI USER, PASSWORD and the SDR values for the sensors you want to use. Runtime collection uses persistent pyghmi IPMI sessions. If `SDRS` is omitted, supported numeric sensors are discovered automatically from pyghmi sensor data.

and you should get something like this (ASUS):

```
5V_AUX           | 01h | ok  |  7.0 | 4.95 Volts
3.3V_AUX         | 02h | ok  |  7.0 | 3.32 Volts
CPU_Vcore        | 03h | ok  |  7.0 | 1.06 Volts
VNN              | 04h | ok  |  7.0 | 0.84 Volts
VCCSRAM          | 05h | ok  |  7.0 | 1.05 Volts
VCCM             | 06h | ok  |  7.0 | 1.21 Volts
1.05V            | 07h | ok  |  7.0 | 1.06 Volts
1.8V             | 08h | ok  |  7.0 | 1.80 Volts
BAT              | 0Bh | ok  |  7.0 | 3.14 Volts
12V              | 0Fh | ok  |  7.0 | 12.10 Volts
MB Temp          | 30h | ok  |  3.0 | 47 degrees C
Card side Temp   | 31h | ok  |  3.0 | 56 degrees C
TR1 Temp         | 32h | ns  |  3.0 | No Reading
CPU1 Temp        | 33h | ok  |  3.0 | 78 degrees C
MemA Temp        | 40h | ok  |  3.0 | 63 degrees C
MemB Temp        | 41h | ok  |  3.0 | 62 degrees C
CPU1_FAN1        | 60h | ok  |  7.0 | 5000 RPM
FRNT_FAN1        | 62h | ok  |  7.0 | 5200 RPM
FRNT_FAN2        | 63h | ok  |  7.0 | 5000 RPM
REAR_FAN1        | 66h | ns  |  7.0 | No Reading

```
The fourth column has the SDR and the first the SUBCLASS

or this (SUPERMICRO):

```
CPU Temp         | 01h | ok  |  3.1 | 77 degrees C
System Temp      | 0Bh | ok  |  7.11 | 71 degrees C
Peripheral Temp  | 0Ch | ok  |  7.12 | 52 degrees C
DIMMA1 Temp      | B0h | ok  | 32.64 | 68 degrees C
DIMMA2 Temp      | B1h | ok  | 32.65 | 66 degrees C
DIMMB1 Temp      | B4h | ok  | 32.68 | 64 degrees C
DIMMB2 Temp      | B5h | ok  | 32.69 | 66 degrees C
FAN1             | 41h | ok  | 29.1 | 1300 RPM
FAN2             | 42h | ok  | 29.2 | 1300 RPM
FAN3             | 43h | ns  | 29.3 | No Reading
FANA             | 44h | ns  | 29.4 | No Reading
12V              | 30h | ok  |  7.48 | 12.06 Volts
5VCC             | 31h | ok  |  7.49 | 5.03 Volts
3.3VCC           | 32h | ok  |  7.50 | 3.35 Volts
VBAT             | 33h | ok  |  7.51 | 3.06 Volts
Vcpu             | 34h | ok  |  3.52 | 1.04 Volts
VDIMM            | 35h | ok  | 32.53 | 1.22 Volts
PVCCSRAM         | 36h | ok  |  7.54 | 1.02 Volts
P1V05_A          | 37h | ok  |  7.55 | 1.05 Volts
5VSB             | 38h | ok  |  7.56 | 4.97 Volts
3.3VSB           | 39h | ok  |  7.57 | 3.30 Volts
PVNN             | 3Ah | ok  |  7.58 | 0.85 Volts
PVPP             | 3Bh | ok  |  7.59 | 2.70 Volts
P1V538_A         | 3Ch | ok  |  7.60 | 1.54 Volts
1.2V BMC         | 3Dh | ok  |  7.61 | 1.22 Volts
PVCC_REF         | 3Eh | ok  |  7.62 | 1.26 Volts

```
The fourth column has the SDR value

or this (DELL 11th generation / iDRAC6):

```
Ambient Temp     | 0Eh | ok  |  7.1 | 20 degrees C
FAN MOD 1A RPM   | 30h | ok  |  7.1 | 4920 RPM
FAN MOD 1B RPM   | 31h | ok  |  7.1 | 4920 RPM
FAN MOD 2A RPM   | 32h | ok  |  7.1 | 4920 RPM
FAN MOD 2B RPM   | 33h | ok  |  7.1 | 4920 RPM
FAN MOD 3A RPM   | 34h | ok  |  7.1 | 4920 RPM
FAN MOD 3B RPM   | 35h | ok  |  7.1 | 4920 RPM
FAN MOD 4A RPM   | 36h | ok  |  7.1 | 2400 RPM
FAN MOD 4B RPM   | 37h | ok  |  7.1 | 2400 RPM
FAN MOD 5A RPM   | 3Bh | ok  |  7.1 | 2400 RPM
FAN MOD 5B RPM   | 3Ah | ok  |  7.1 | 2400 RPM
Current          | 94h | ok  | 10.1 | 0.60 Amps
Current          | 95h | ok  | 10.2 | 0.60 Amps
Voltage          | 96h | ok  | 10.1 | 226 Volts
Voltage          | 97h | ok  | 10.2 | 226 Volts
System Level     | 98h | ok  |  7.1 | 287 Watts
```

For DELL servers, the fourth column is the SDR value and the first column is the SUBCLASS. Some DELL rows share the same SDR value, so configure both `VALUE` and `SUBCLASS`.

For DELL 11th generation / iDRAC6 servers, `SDRS` is optional. If you configure only `IPMI_NODENAME`, `BRAND`, `IPMI_IP`, `IPMI_USER`, and `IPMI_PASSWORD`, the script publishes every visible numeric sensor exposed by pyghmi. The MQTT node path is derived from `IPMI_NODENAME`, so choose a node name that is unique in your infrastructure. Names are published as configured or discovered; MQTT path segments and Home Assistant IDs are only sanitized enough to be valid. Add `SDRS` only when you want to limit or override the published sensors.

DELL discovery is diffed between collection cycles. New or changed sensors publish their retained state and discovery payloads, unchanged sensors are left alone, and sensors that disappear from IPMI output have their retained discovery and state payloads cleared.

On DELL/iDRAC6 with full SDR auto-discovery, the first pyghmi SDR cache warm-up can take several seconds. In that case a one-second `TIME_PERIOD` means “poll again on the next available fixed-rate tick,” not “guarantee one full SDR snapshot per second during warm-up.” Use the logs and poll metrics to confirm whether collection overruns the requested period on your BMC.

## Home Assistant Direct Use

The shared IPMI core is intentionally adapter-friendly, but this project does not currently ship a direct Home Assistant integration. MQTT remains the supported Home Assistant path because it can update entities through retained discovery and state messages without requiring a Home Assistant restart. A direct integration should only be added if it can use a reloadable config-entry style workflow and keep updates restart-free.


to connect to your server and see all of the available sensors and their SDR value.



```
SERVERS:
      - IPMI_NODENAME: SERVER NAME
        BRAND: SERVER BRAND
        IPMI_IP: SERVER IPMI IP
        IPMI_USER: 'SERVER IPMI USER'
        IPMI_PASSWORD: 'SERVER IPMI PASSWORD'
        SDRS: # OPTIONAL FOR DELL 11TH GENERATION / iDRAC6; REQUIRED FOR ASUS AND SUPERMICRO
            - SDR_TYPE: TYPE OF SDR (a number to match the dictionary of types in topics)
              SDR_CLASS: ENTITY CLASS FOR HA (CAN BE temperature, temperaturef for fahrenheit, frequency, voltage, current, power or fan, units will be C, F, Hz, V, A, W or RPM accordingly)
              SUBCLASS: SENSOR NAME AS EXPOSED BY THE BMC, for example Mb Temp or Ambient Temp
              VALUE: SDR VALUE 

```

After configuring this, the first time you run the script it will create the devices and its entities directly in your MQTT broker you will find them on Home Assistant in the MQTT broker's entity page as well as separate devices(one per server). The entities are grouped into a each server which will appear as a device,  you can edit it to add it to an area.


The program generates a log that will grow to 10MiB and then cycle 2 times (that is, there will be no more than 30MiB of logs).
