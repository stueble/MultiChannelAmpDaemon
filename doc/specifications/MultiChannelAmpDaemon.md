# Multi-Channel Amplifier Control Daemon - Technical Specification

## Version: 1.1.0

## Overview
A Python daemon for Raspberry Pi 5 that controls a multi-channel amplifier system with three 8-channel USB sound cards and a main power supply. The daemon monitors Squeezelite instances and manages power states based on playback activity. It exports system status via JSON file for monitoring tools like Telegraf.

## System Architecture

### Hardware Components
- **Raspberry Pi 5** running the daemon
- **Main Power Supply** controlled via GPIO 13
  - GPIO HIGH (1) = Power OFF
  - GPIO LOW (0) = Power ON
- **Three 8-channel USB Sound Cards** (KAB9_1, KAB9_2, KAB9_3)
  - Each controlled via 3 GPIO pins: SUSPEND, MUTE, LED
  - Optional: 1-wire temperature sensor per sound card
- **Error LED** on GPIO 26

### Sound Card Configuration

#### KAB9_1
- ALSA Card: 4
- USB Device: 1-2
- GPIO SUSPEND: 12
- GPIO MUTE: 16
- GPIO LED: 17
- Temperature Sensor: 28-00000abcdef0 (optional, DS18B20)
- Players: wohnzimmer, tvzimmer, kueche, gaestezimmer

#### KAB9_2
- ALSA Card: 3
- USB Device: 3-1
- GPIO SUSPEND: 6
- GPIO MUTE: 25
- GPIO LED: 27
- Temperature Sensor: 28-00000fedcba9 (optional)
- Players: schlafzimmer, terrasse, gwc, elternbad, balkon, sauna

#### KAB9_3
- ALSA Card: 0
- USB Device: 1-1
- GPIO SUSPEND: 23
- GPIO MUTE: 24
- GPIO LED: 22
- Temperature Sensor: (optional)
- Players: kian, sarina, hobbyraum

## Functional Requirements

### Core Behavior

1. **Initial State**
   - All sound cards: SUSPENDED (GPIO SUSPEND=HIGH, MUTE=HIGH, LED=LOW)
   - Power supply: OFF (GPIO=HIGH)
   - Error LED: OFF (GPIO=LOW)

2. **Player Activation (Squeezelite starts playback)**
   - Activate main power supply immediately
   - Activate associated sound card with sequence:
     1. Set SUSPEND GPIO to LOW
     2. Wait 1 second (GPIO_DELAY)
     3. Set MUTE GPIO to LOW
     4. Set LED GPIO to HIGH
   - Cancel any pending deactivation timers for power supply

3. **Player Deactivation (Squeezelite stops playback)**
   - Remove player from active list
   - If no players on that sound card are active:
     - Schedule sound card deactivation after 15 minutes (SOUNDCARD_TIMEOUT)
   - Check if power supply can be deactivated

4. **Sound Card Deactivation (after timeout)**
   - Sequence with mute-to-suspend delay:
     1. Set MUTE GPIO to HIGH
     2. Wait SOUNDCARD_MUTE_DELAY seconds (default 5 seconds)
     3. Check if players became active during delay - if yes, abort and unmute
     4. Set SUSPEND GPIO to HIGH
     5. Wait GPIO_DELAY
     6. Set LED GPIO to LOW
   - After deactivation, trigger power supply deactivation check

5. **Power Supply Deactivation**
   - Only if ALL sound cards are inactive
   - Schedule deactivation after 30 minutes (POWER_SUPPLY_TIMEOUT)
   - Set GPIO to HIGH (OFF)

### Timeout Configuration

**Normal Mode:**
- SOUNDCARD_TIMEOUT: 15 minutes (900 seconds)
- SOUNDCARD_MUTE_DELAY: 5 seconds
- POWER_SUPPLY_TIMEOUT: 30 minutes (1800 seconds)
- GPIO_DELAY: 1.0 seconds
- STATUS_UPDATE_INTERVAL: 30 seconds

**Debug Mode (--debug flag):**
- SOUNDCARD_TIMEOUT: 1 minute (60 seconds)
- POWER_SUPPLY_TIMEOUT: 2 minutes (120 seconds)
- SOUNDCARD_MUTE_DELAY: 2 seconds
- Timeout values displayed in startup banner

### Configuration File

**Location:** `/etc/MultiChannelAmpDaemon.yaml`

**Structure:**
```yaml
global:
  soundcard_timeout: 900
  soundcard_mute_delay: 5
  power_supply_timeout: 1800
  gpio_delay: 1.0
  gpio_power_supply: 13
  gpio_error_led: 26
  socket_path: /var/run/MultiChannelAmpDaemon.sock
  pid_file: /var/run/MultiChannelAmpDaemon.pid
  status_file: /var/run/MultiChannelAmpDaemon.status
  log_file: /var/log/MultiChannelAmpDaemon.log
  log_level: INFO

squeezelite:
  binary: /usr/bin/squeezelite
  callback_script: /usr/local/bin/MultiChannelAmpCallback.py
  common_options:
    - "-a 80:4::"
    - "-b 500:2000"
  lms_server: 192.168.1.100

soundcards:
  - id: 1
    name: KAB9_1
    alsa_card: "4"
    usb_device: "1-2"
    temp_sensor: "28-00000abcdef0"  # Optional
    gpio:
      suspend: 12
      mute: 16
      led: 17
    players:
      - name: wohnzimmer
        alsa_device: "hw:4,0"
        mac_address: "aa:bb:cc:dd:ee:01"
```

### Communication Protocol

#### Unix Socket Interface
- **Socket Path:** `/var/run/MultiChannelAmpDaemon.sock`
- **Permissions:** 0666 (readable/writable by all)
- **Protocol:** Text-based, line-delimited
- **Message Format:** `playername:state\n`
  - playername: Name of the Squeezelite player
  - state: `1` for play, `0` for stop, `2` for pause
- **Response:** `OK\n`

#### Squeezelite Integration
- Each Squeezelite instance uses `-S` parameter to call callback script
- Squeezelite calls: `<script> <state>` (only state, not player name)
- Callback script must include player name in its invocation
- Example: `squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer" -o hw:4,0`

### Status File Export

#### JSON Status File
- **Location:** `/var/run/MultiChannelAmpDaemon.status.json`
- **Update Interval:** Every 30 seconds
- **Write Method:** Atomic (write to .tmp file, then rename)
- **Permissions:** Readable by all

#### Status File Structure
```json
{
  "timestamp": 1738366800.123,
  "power_supply": {
    "state": "on",
    "active": true
  },
  "error_led": {
    "state": "off",
    "active": false
  },
  "soundcards": {
    "1": {
      "id": 1,
      "name": "KAB9_1",
      "state": "on",
      "active": true,
      "active_players": ["wohnzimmer", "kueche"],
      "player_count": 2,
      "temperature": 45.3,
      "temp_sensor": "28-00000abcdef0"
    },
    "2": {
      "id": 2,
      "name": "KAB9_2",
      "state": "suspended",
      "active": false,
      "active_players": [],
      "player_count": 0,
      "temperature": 28.5,
      "temp_sensor": "28-00000fedcba9"
    }
  }
}
```

#### Soundcard States
- **`on`**: Has active players (len(activePlayers) > 0)
- **`muted`**: Active but no players (edge case, shouldn't normally occur)
- **`suspended`**: Deactivated (state == OFF)

#### Temperature Reading
- Reads from `/sys/bus/w1/devices/{sensor_id}/w1_slave`
- Format: DS18B20 1-wire temperature sensors
- Value in Celsius (e.g., 45.3)
- Returns `null` if:
  - No sensor configured for soundcard
  - Sensor not found
  - CRC check failed
  - Parse error
- Non-blocking: Temperature read errors do not affect daemon operation

## Error Handling

### Critical Error Response
When a critical error occurs, execute in this order:
1. Log critical error message
2. Turn ON error LED (GPIO 26 = HIGH), set errorLedActive = True
3. Deactivate all sound cards (force immediate shutdown)
4. Deactivate power supply (GPIO 13 = HIGH)
5. Write final status to JSON file

### Normal Shutdown
When daemon stops normally (SIGTERM, SIGINT):
1. Turn ON error LED (indicates daemon not running), set errorLedActive = True
2. Stop status update timer
3. Write final status to JSON file
4. Close Unix socket
5. Remove PID file, status file, JSON status file
6. Exit

### Daemon Instance Protection
- Use PID file at `/var/run/MultiChannelAmpDaemon.pid`
- Check if daemon already running on startup
- Verify process exists with `os.kill(pid, 0)`
- Remove stale PID files if process doesn't exist
- Exit with error if daemon already running

## Threading and Concurrency

### Thread Safety
- **SoundcardController:** Uses threading.Lock for state modifications
- **PowerSupplyController:** Uses threading.Lock for state modifications
- **isActive() methods:** Do NOT use locks to prevent deadlock
  - Reading enum state is atomic and thread-safe
- **Timer threads:** All timer threads are daemon threads
- **Status update thread:** Daemon timer thread updates status file periodically

### Socket Server Threading
- Main socket server thread accepts connections
- Each client connection handled in separate daemon thread
- Non-blocking socket operations with proper exception handling

### Deadlock Prevention
The `isActive()` methods in SoundcardController and PowerSupplyController must NOT use locks because:
- They are called from within locked sections of other methods
- Reading an enum value is atomic in Python
- Using locks here causes deadlock when `deactivate()` (which holds a lock) calls `daemon.checkPowerSupplyDeactivation()` which calls `isActive()`

### Power Supply Timer Cancellation
The power supply activation must ALWAYS be called when a player starts, not only when power supply is OFF:
- `handlePlayerEvent()` must call `powerSupply.activate()` unconditionally
- `activate()` must cancel pending timer BEFORE checking if already active
- This ensures pending shutdown timers are cancelled when new playback starts

## File Structure

### Two Python Files

#### 1. MultiChannelAmpDaemon.py (Main Daemon)
**Purpose:** Background daemon that manages power supply and sound card states

**Version:** 1.1.0

**Key Components:**
- **Version Constant:** `VERSION = "1.1.0"`
- **Configuration Constants:** 
  - SOUNDCARD_TIMEOUT, SOUNDCARD_MUTE_DELAY, POWER_SUPPLY_TIMEOUT
  - GPIO_DELAY, GPIO_ERROR_LED, GPIO_POWER_SUPPLY
  - STATUS_UPDATE_INTERVAL = 30
  - File paths: STATUS_JSON_FILE, PID_FILE, SOCKET_PATH
  - DEFAULT_CONFIG_PATH = "/etc/MultiChannelAmpDaemon.yaml"
- **Enums:** DeviceState (OFF, ON)
- **Data Classes:** SoundcardConfig (id, name, gpioSuspend, gpioMute, gpioLed, alsaCard, usbDevice, tempSensor, players)
- **Classes:**
  - `SoundcardController`: Manages individual sound card via GPIO, includes daemon reference
  - `PowerSupplyController`: Manages main power supply via GPIO
  - `AmpControlDaemon`: Main daemon orchestrating the system
- **Utility Functions:**
  - `loadConfiguration(configPath)`: Load YAML config
  - `checkAlreadyRunning()`: Verifies no other daemon instance is running
  - `writePidFile()`: Creates PID file with current process ID
  - `main()`: Entry point with argument parsing
- **Daemon Methods:**
  - `readTemperature(sensorId)`: Read 1-wire DS18B20 sensor
  - `getStatus()`: Build complete status dictionary
  - `writeStatusFile()`: Write status JSON atomically
  - `scheduleStatusUpdate()`: Periodic status updates every 30s
- **Command-line Interface:**
  - `--debug`: Enable debug mode (1min/2min timeouts, DEBUG logging)
  - `--config`: Path to config file (default: /etc/MultiChannelAmpDaemon.yaml)
  - `--version`: Display version number

**Dependencies:**
- Standard library: sys, time, threading, logging, signal, socket, os, argparse, yaml
- Platform-specific: RPi.GPIO (or lgpio for Pi 5)

**Execution:** Runs as background daemon, listens on Unix socket for events

#### 2. MultiChannelAmpCallback.py (Callback Script)
**Purpose:** Lightweight script invoked by Squeezelite to notify daemon of playback events

**Key Components:**
- **Socket Communication:** Connects to `/var/run/MultiChannelAmpDaemon.sock`
- **Message Protocol:** Sends `playername:state\n` format
- **Timeout Handling:** 5-second connection timeout
- **Error Handling:** Proper error messages for connection failures
- **Exit Codes:** 0 on success, 1 on failure
- **Logging:** Writes to `/var/log/MultiChannelAmpCallback.log` for debugging

**Execution:** Called by Squeezelite via `-S` parameter with 2 arguments:
```
MultiChannelAmpCallback.py <playername> <state>
```
Where state is passed by Squeezelite (0=stop, 1=play, 2=pause)

**Integration Example:**
```bash
squeezelite -n wohnzimmer \
  -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer" \
  -o hw:4,0 &
```

#### 3. MultiChannelAmpDaemon.yaml (Configuration File)
**Location:** `/etc/MultiChannelAmpDaemon.yaml`

Contains complete system configuration including:
- Global timeouts and GPIO pins
- Squeezelite binary path and common options
- Soundcard definitions with GPIO mappings, temperature sensors, and player assignments

## Code Style Requirements

### Naming Conventions
- **Functions and Methods:** camelCase (e.g., `activatePlayer()`, `setupGpio()`, `readTemperature()`)
- **Variables:** camelCase (e.g., `playerName`, `soundcardId`, `tempSensor`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `SOUNDCARD_TIMEOUT`, `GPIO_DELAY`, `STATUS_UPDATE_INTERVAL`)
- **Classes:** PascalCase (e.g., `SoundcardController`, `AmpControlDaemon`)

### Language
- All code, comments, and docstrings in English
- Clear, descriptive variable names
- Comprehensive docstrings for all classes and methods

## Logging

### Log Configuration
- **Default Level:** INFO
- **Debug Mode Level:** DEBUG
- **Log File:** `/var/log/MultiChannelAmpDaemon.log`
- **Console Output:** Yes (StreamHandler)
- **Format:** `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

### Startup Banner
```
================================================================================
=                                                                              =
=  MULTI-CHANNEL AMP DAEMON STARTING                                          =
=  Version: 1.1.0                                                             =
=                                                                              =
================================================================================
```

In debug mode, also show timeouts:
```
================================================================================
=                                                                              =
=  MULTI-CHANNEL AMP DAEMON STARTING (DEBUG MODE)                             =
=  Version: 1.1.0                                                             =
=  Soundcard timeout: 60s, Power supply timeout: 120s                         =
=                                                                              =
================================================================================
```

### Key Log Messages
- INFO: Player events, state changes, timer scheduling, status file updates
- DEBUG: GPIO state changes (SUSPEND, MUTE, LED values), temperature readings
- WARNING: Unknown players, temperature sensor failures
- ERROR: GPIO failures, socket errors, status file write errors
- CRITICAL: Fatal errors triggering emergency shutdown

## Installation and Deployment

### File Installation
```bash
# Create config directory
sudo mkdir -p /etc

# Install configuration
sudo cp MultiChannelAmpDaemon.yaml /etc/

# Install daemon
sudo cp MultiChannelAmpDaemon.py /usr/local/bin/
sudo chmod +x /usr/local/bin/MultiChannelAmpDaemon.py

# Install callback script
sudo cp MultiChannelAmpCallback.py /usr/local/bin/
sudo chmod +x /usr/local/bin/MultiChannelAmpCallback.py
```

### Starting the Daemon
```bash
# Normal mode
sudo /usr/local/bin/MultiChannelAmpDaemon.py

# With custom config
sudo /usr/local/bin/MultiChannelAmpDaemon.py --config /path/to/config.yaml

# Debug mode (shorter timeouts, verbose logging)
sudo /usr/local/bin/MultiChannelAmpDaemon.py --debug

# Check version
/usr/local/bin/MultiChannelAmpDaemon.py --version
```

### Systemd Service
Service file at `/etc/systemd/system/MultiChannelAmpDaemon.service`:

```ini
[Unit]
Description=Multi-Channel Amplifier Control Daemon
After=network.target sound.target

[Service]
Type=simple
ExecStart=/usr/local/bin/MultiChannelAmpDaemon.py --config /etc/MultiChannelAmpDaemon.yaml
Restart=on-failure
RestartSec=5s
User=root
Group=root
PIDFile=/var/run/MultiChannelAmpDaemon.pid

[Install]
WantedBy=multi-user.target
```

### 1-Wire Temperature Sensor Setup
```bash
# Load kernel modules
sudo modprobe w1-gpio
sudo modprobe w1-therm

# Make persistent
echo "w1-gpio" | sudo tee -a /etc/modules
echo "w1-therm" | sudo tee -a /etc/modules

# Find sensors
ls -la /sys/bus/w1/devices/
# Shows sensor IDs like: 28-00000abcdef0

# Test reading
cat /sys/bus/w1/devices/28-00000abcdef0/w1_slave
```

## Expected Behavior Examples

### Example 1: Single Player Session with Temperature Monitoring
1. Daemon starts, all OFF, reads temperatures (if configured)
2. Player "wohnzimmer" starts playback → Power ON, KAB9_1 activates
3. Temperature monitored every 30 seconds → 45.3°C recorded in status
4. Player "wohnzimmer" stops → KAB9_1 schedules deactivation (15 min)
5. After 15 min → KAB9_1 mutes, waits 5s, then suspends
6. Power supply schedules deactivation (30 min)
7. After 30 min → Power supply turns OFF

### Example 2: Mute Delay Interruption
1. Player stops → Soundcard mute timer starts (15 min)
2. After 15 min → MUTE goes HIGH
3. During 5s mute delay → Player starts again
4. Deactivation cancelled, MUTE goes LOW again
5. Playback continues normally

### Example 3: Status File Monitoring
1. External tool reads `/var/run/MultiChannelAmpDaemon.status.json`
2. Sees KAB9_1 state: "on", temperature: 45.3°C, 2 active players
3. Telegraf ingests this every 30 seconds
4. Grafana displays temperature trends and player activity

## Security Considerations

- Socket permissions (0666) allow any user to send events - assumes trusted local system
- Daemon must run as root for GPIO access
- PID file prevents multiple daemon instances
- No authentication on socket interface
- Input validation on socket messages enforces "name:0/1/2" format
- Unknown player names are logged but ignored
- Only accepts integer state values 0, 1, or 2
- Status JSON file world-readable for monitoring tools

## Future Extension Points

### Potential Enhancements
1. **USB/ALSA Power Management:** Use alsaCard and usbDevice fields for USB suspend/resume
2. **Web Interface:** HTTP API for monitoring and control
3. **MQTT Integration:** Publish state changes to MQTT broker
4. **Metrics Endpoint:** Built-in Prometheus exporter
5. **Hot-reload:** Reload configuration without restart
6. **Multiple Temperature Sensors:** Support multiple sensors per soundcard
7. **Fan Control:** PWM fan control based on temperature readings
8. **Alert System:** Temperature threshold alerts

### Version Management
- Current: 1.1.0
- Increment PATCH (1.1.x) for bug fixes
- Increment MINOR (1.x.0) for new features (backward compatible)
- Increment MAJOR (x.0.0) for breaking changes
- Update VERSION constant, docstring, and startup banner
- Document changes in commit messages

## Testing Considerations

### Debug Mode
Use `--debug` flag for faster testing:
- 1-minute sound card timeout instead of 15 minutes
- 2-minute power supply timeout instead of 30 minutes
- 2-second mute delay instead of 5 seconds
- DEBUG level logging for detailed GPIO and temperature information
- Timeout values displayed in startup banner

### Manual Testing
```bash
# Start daemon in debug mode
sudo /usr/local/bin/MultiChannelAmpDaemon.py --debug

# Simulate player events
echo "wohnzimmer:1" | nc -U /var/run/MultiChannelAmpDaemon.sock
echo "wohnzimmer:0" | nc -U /var/run/MultiChannelAmpDaemon.sock

# Monitor status file
watch -n 1 'jq "." /var/run/MultiChannelAmpDaemon.status.json'

# Check temperatures
jq '.soundcards[] | {name, temperature}' /var/run/MultiChannelAmpDaemon.status.json

# Monitor logs
tail -f /var/log/MultiChannelAmpDaemon.log
```
