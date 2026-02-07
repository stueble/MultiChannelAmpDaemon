# Multi-Channel Amplifier Control Daemon - Technical Specification

## Version: 1.3.0

## Overview
A Python daemon for Raspberry Pi 5 that controls a multi-channel amplifier system with three 8-channel USB sound cards and a main power supply. The daemon monitors Squeezelite instances and manages power states based on playback activity. It exports system status via JSON file for monitoring tools like Telegraf.

## System Architecture

### Hardware Components
- **Raspberry Pi 5** running the daemon
- **Main Power Supply** controlled via GPIO 13 (configurable)
  - **INVERTED LOGIC (for safety):**
  - GPIO LOW (0) = Power OFF
  - GPIO HIGH (1) = Power ON
  - Safety feature: Raspberry Pi shutdown/failure automatically turns off power supply
- **Three 8-channel USB Sound Cards** (KAB9_1, KAB9_2, KAB9_3)
  - Each controlled via 3 GPIO pins: SUSPEND, MUTE, LED
  - Optional: 1-wire temperature sensor per sound card
- **Error LED** on GPIO 26 (configurable)

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
   - All sound cards: SUSPENDED (GPIO SUSPEND=HIGH, MUTE=HIGH, LED=LOW, state=DeviceState.SUSPENDED)
   - Power supply: OFF (GPIO=LOW, inverted logic, state=PowerState.OFF)
   - Error LED: OFF (GPIO=LOW)

2. **Player Activation (Squeezelite starts playback)**
   - Activate main power supply immediately (always call activate() to cancel pending timers)
   - Activate associated sound card based on current state:
     - If SUSPENDED: call `resume()` → SUSPEND LOW → wait 1s → MUTE LOW → LED HIGH → state=ON
     - If MUTED: call `unmute()` → MUTE LOW → state=ON
     - If already ON: no action needed
   - Cancel any pending suspend timers for that sound card

3. **Player Deactivation (Squeezelite stops playback)**
   - Remove player from active list
   - If no players on that sound card are active:
     - Call `mute()` → MUTE GPIO HIGH → state=MUTED
     - Schedule suspend after 15 minutes (SOUNDCARD_TIMEOUT)
   - Check if power supply can be deactivated

4. **Sound Card Suspend (after timeout)**
   - Sequence with mute-to-suspend delay:
     1. Verify MUTE GPIO is HIGH (state should be MUTED)
     2. Wait SOUNDCARD_MUTE_DELAY seconds (default 5 seconds)
     3. Check if players became active during delay - if yes, call `unmute()` and abort
     4. Set SUSPEND GPIO to HIGH
     5. Wait GPIO_DELAY
     6. Set LED GPIO to LOW
     7. Set state=SUSPENDED
   - After suspend, trigger power supply deactivation check

5. **Power Supply Deactivation**
   - Only if ALL sound cards are inactive
   - Schedule deactivation after 30 minutes (POWER_SUPPLY_TIMEOUT)
   - Set GPIO to LOW (OFF, inverted logic)

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
- SOUNDCARD_MUTE_DELAY: 5 seconds (unchanged in debug mode)
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
  },
  "players": {
    "wohnzimmer": {
      "name": "Wohnzimmer",
      "active": true,
      "soundcard_id": 1,
      "soundcard_name": "KAB9_1"
    },
    "schlafzimmer": {
      "name": "Schlafzimmer",
      "active": false,
      "soundcard_id": 2,
      "soundcard_name": "KAB9_2"
    },
    "kueche": {
      "name": "Küche",
      "active": true,
      "soundcard_id": 1,
      "soundcard_name": "KAB9_1"
    }
  }
}
```

**Note:** The `players` section uses the player `description` field from the configuration in the `name` field for better readability (with umlauts and special characters).

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
4. Deactivate power supply (GPIO 13 = LOW, inverted logic)
5. Write final status to JSON file

### Normal Shutdown
When daemon stops normally (SIGTERM, SIGINT):
1. Stop status update timer
2. Mute and suspend all sound cards (MUTE HIGH → SUSPEND HIGH → LED LOW)
3. Deactivate power supply (GPIO = LOW, inverted logic)
4. Turn ON error LED (indicates daemon not running), set errorLedActive = True
5. Write final status to JSON file
6. Close Unix socket
7. Remove PID file, status file, JSON status file
8. Exit

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

### Immediate Mute on Player Deactivation
When all players on a soundcard become inactive:
- `muteImmediately()` is called from within the locked context of `deactivatePlayer()`
- MUTE GPIO is set to HIGH immediately (no delay)
- This prevents audio pops/clicks when playback stops
- Full suspend (SUSPEND GPIO HIGH) is delayed by SOUNDCARD_TIMEOUT
- During the mute-to-suspend delay, playback can resume and unmute the card

## File Structure

### Two Python Files

#### 1. MultiChannelAmpDaemon.py (Main Daemon)
**Purpose:** Background daemon that manages power supply and sound card states

**Version:** 1.3.0

**Key Components:**
- **Version Constant:** `VERSION = "1.3.0"`
- **Configuration Constants:** 
  - SOUNDCARD_TIMEOUT, SOUNDCARD_MUTE_DELAY, POWER_SUPPLY_TIMEOUT
  - GPIO_DELAY, GPIO_ERROR_LED, GPIO_POWER_SUPPLY
  - STATUS_UPDATE_INTERVAL = 30
  - File paths: STATUS_JSON_FILE, PID_FILE, SOCKET_PATH, STATUS_FILE
  - DEFAULT_CONFIG_PATH = "/etc/MultiChannelAmpDaemon.yaml"
- **Enums:** 
  - DeviceState (SUSPENDED=0, MUTED=1, ON=2)
  - PowerState (OFF=0, ON=1)
- **Data Classes:** SoundcardConfig (id, name, gpioSuspend, gpioMute, gpioLed, alsaCard, usbDevice, tempSensor, players: Dict[str, str])
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
  - `getStatus()`: Build complete status dictionary including players section
  - `writeStatusFile()`: Write status JSON atomically
  - `scheduleStatusUpdate()`: Periodic status updates every 30s
  - `handleError()`: Critical error handler that activates error LED and shuts down
- **SoundcardController Methods:**
  - `activatePlayer(playerName)`: Adds player to active set, cancels timers, calls resume() or unmute()
  - `deactivatePlayer(playerName)`: Removes player, calls mute(), schedules suspend
  - `resume()`: Resume from SUSPENDED (SUSPEND LOW → wait → MUTE LOW → LED HIGH → state=ON)
  - `unmute()`: Unmute from MUTED (MUTE LOW → state=ON)
  - `mute()`: Mute sound card (MUTE HIGH → state=MUTED)
  - `suspend()`: Suspend sound card (ensure MUTE HIGH → wait delay → SUSPEND HIGH → LED LOW → state=SUSPENDED)
  - `scheduleSuspend()`: Schedules suspend() after SOUNDCARD_TIMEOUT
  - `isActive()`: Returns True if state != SUSPENDED
  - `isMuted()`: Returns True if state == MUTED
  - `isSuspended()`: Returns True if state == SUSPENDED
- **PowerSupplyController Methods:**
  - `activate()`: Cancels timer FIRST, then sets GPIO HIGH (ON, inverted)
  - `scheduleDeactivation()`: Schedules deactivate() after POWER_SUPPLY_TIMEOUT
  - `deactivate()`: Sets GPIO LOW (OFF, inverted) to turn off
  - `setupGpio()`: Initializes GPIO with LOW (OFF) state for safety
- **Command-line Interface:**
  - `--debug`: Enable debug mode (1min/2min timeouts, DEBUG logging)
  - `--config`: Path to config file (default: /etc/MultiChannelAmpDaemon.yaml)
  - `--version`: Display version number

**Dependencies:**
- Standard library: sys, time, threading, logging, signal, socket, os, argparse, yaml, pathlib, typing, dataclasses, enum
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
- **Functions and Methods:** camelCase (e.g., `activatePlayer()`, `setupGpio()`, `readTemperature()`, `muteImmediately()`)
- **Variables:** camelCase (e.g., `playerName`, `soundcardId`, `tempSensor`, `errorLedActive`)
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
=  Version: 1.3.0                                                             =
=                                                                              =
================================================================================
```

In debug mode, also show timeouts:
```
================================================================================
=                                                                              =
=  MULTI-CHANNEL AMP DAEMON STARTING (DEBUG MODE)                             =
=  Version: 1.3.0                                                             =
=  Soundcard timeout: 60s, Power supply timeout: 120s                         =
=                                                                              =
================================================================================
```

### Key Log Messages
- INFO: Player events, state changes, timer scheduling, status file updates, timer cancellations
- DEBUG: GPIO state changes (SUSPEND, MUTE, LED values), temperature readings, mute delay waits
- WARNING: Unknown players, temperature sensor failures, stale PID files
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
1. Daemon starts, all OFF, power supply GPIO=LOW (OFF, inverted), reads temperatures (if configured)
2. Player "wohnzimmer" starts playback → Power GPIO=HIGH (ON, inverted), KAB9_1 activates
3. Temperature monitored every 30 seconds → 45.3°C recorded in status
4. Player "wohnzimmer" stops → KAB9_1 **mutes immediately**, schedules suspend (15 min)
5. After 15 min → KAB9_1 waits 5s mute delay, then suspends (SUSPEND HIGH, LED LOW)
6. Power supply schedules deactivation (30 min)
7. After 30 min → Power supply GPIO=LOW (OFF, inverted)

### Example 2: Mute Delay Interruption
1. Player stops → Soundcard **muted immediately**, suspend timer starts (15 min)
2. After 15 min → Suspend starts, waits 5s mute delay
3. During 5s mute delay → Player starts again
4. Suspend cancelled, MUTE goes LOW again, LED stays HIGH
5. Playback continues normally

### Example 3: Status File Monitoring with Players Section
1. External tool reads `/var/run/MultiChannelAmpDaemon.status.json`
2. Sees KAB9_1 state: "on", temperature: 45.3°C, 2 active players
3. Sees players section with individual player status for all configured players
4. Telegraf ingests this every 30 seconds
5. Grafana displays temperature trends and player activity

### Example 4: Power Supply Timer Cancellation
1. Player stops → Power supply schedules shutdown (30 min)
2. After 25 minutes → Another player starts
3. Power supply activation called → **pending timer cancelled**
4. Power stays ON, no restart needed (already active)

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
- Current: 1.3.0
- Increment PATCH (1.3.x) for bug fixes
- Increment MINOR (1.x.0) for new features (backward compatible)
- Increment MAJOR (x.0.0) for breaking changes
- Update VERSION constant, docstring, and startup banner
- Document changes in commit messages

## Testing Considerations

### Debug Mode
Use `--debug` flag for faster testing:
- 1-minute sound card timeout instead of 15 minutes
- 2-minute power supply timeout instead of 30 minutes
- SOUNDCARD_MUTE_DELAY remains 5 seconds (unchanged)
- DEBUG level logging for detailed GPIO and temperature information
- Timeout values displayed in startup banner

### Manual Testing
```bash
# Start daemon in debug mode
sudo /usr/local/bin/MultiChannelAmpDaemon.py --debug

# Simulate player events
echo "wohnzimmer:1" | nc -U /var/run/MultiChannelAmpDaemon.sock
echo "wohnzimmer:0" | nc -U /var/run/MultiChannelAmpDaemon.sock

# Monitor status file (including players section)
watch -n 1 'jq "." /var/run/MultiChannelAmpDaemon.status.json'

# Check temperatures
jq '.soundcards[] | {name, temperature}' /var/run/MultiChannelAmpDaemon.status.json

# Check individual player status
jq '.players' /var/run/MultiChannelAmpDaemon.status.json

# Monitor logs for immediate mute
tail -f /var/log/MultiChannelAmpDaemon.log | grep -E "(Muting|MUTE)"
```

## Changes from Version 1.1.0 to 1.2.0

### Major Changes
1. **Immediate Mute on Stop:** When a player stops, MUTE is now set HIGH immediately (in `muteImmediately()`), not after SOUNDCARD_TIMEOUT
2. **Players Section in Status:** Added dedicated `players` section in JSON status with individual player status
3. **Enhanced Error Handling:** `handleError()` method properly activates error LED and performs emergency shutdown
4. **Improved Timer Cancellation:** Power supply `activate()` always cancels pending timers first
5. **Configuration Loading:** GPIO pins now configurable via YAML (gpio_power_supply, gpio_error_led)

### Implementation Details
- `deactivatePlayer()` now calls `muteImmediately()` when last player stops
- `deactivate()` verifies MUTE is already HIGH before mute delay
- `getStatus()` builds players section from all configured soundcard players
- Error LED state tracked with `errorLedActive` boolean flag
- Enhanced logging for mute operations and timer cancellations

### Backward Compatibility
- Configuration file format unchanged
- Socket protocol unchanged
- Status file adds new `players` section (additive change)
- All existing monitoring tools continue to work

## Changes from Version 1.2.0 to 1.2.1

### Safety Enhancement
1. **Inverted Power Supply Logic:** Power supply GPIO control inverted for safety
   - **Before (1.2.0):** GPIO HIGH = OFF, GPIO LOW = ON
   - **After (1.2.1):** GPIO LOW = OFF, GPIO HIGH = ON
   - **Reason:** If Raspberry Pi crashes, shuts down, or loses power, GPIO pins default to LOW, automatically turning OFF the power supply
   - This prevents the amplifier power supply from staying on indefinitely in case of system failure

### Implementation Details
- `PowerSupplyController.setupGpio()`: Initializes GPIO to LOW (OFF)
- `PowerSupplyController.activate()`: Sets GPIO to HIGH (ON)
- `PowerSupplyController.deactivate()`: Sets GPIO to LOW (OFF)
- `handleError()`: Emergency shutdown sets GPIO to LOW (OFF)
- Updated all log messages to reflect inverted logic
- Class docstring updated: "Controls the main power supply via GPIO (inverted logic for safety)"

### Hardware Impact
- **BREAKING CHANGE:** External circuit must be inverted to match new logic
- Requires hardware modification: relay or transistor circuit must respond to HIGH=ON instead of LOW=ON
- Significantly improves system safety in case of Raspberry Pi failure

### Backward Compatibility
- **NOT backward compatible** with hardware designed for v1.2.0
- Configuration file format unchanged
- Socket protocol unchanged
- Status file format unchanged
- Monitoring tools unaffected

## Changes from Version 1.2.2 to 1.3.0

### Major Refactoring - Cleaner State Machine
This is a **MINOR version bump** due to significant internal refactoring, though the external API remains compatible.

### 1. New State Machine with Three States
**DeviceState Enum:**
- `SUSPENDED = 0`: Fully off (SUSPEND=HIGH, MUTE=HIGH, LED=LOW)
- `MUTED = 1`: Active but muted (SUSPEND=LOW, MUTE=HIGH, LED=HIGH)
- `ON = 2`: Active and unmuted (SUSPEND=LOW, MUTE=LOW, LED=HIGH)

**PowerState Enum** (separate for power supply):
- `OFF = 0`
- `ON = 1`

**Previous State Model (v1.2.2):**
- Only two states: OFF and ON
- MUTED state was implicit (not tracked)

### 2. Cleaner Method Names
**Before (v1.2.2) → After (v1.3.0):**
- `activate()` → `resume()` (from suspended) + `unmute()` (from muted)
- `deactivate()` → `suspend()` (to suspended)
- `muteImmediately()` → `mute()` (to muted state)
- `scheduleDeactivation()` → `scheduleSuspend()`

**New Helper Methods:**
- `isActive()`: Returns True if not suspended
- `isMuted()`: Returns True if muted
- `isSuspended()`: Returns True if suspended

### 3. Fixed Bug: Unmuting When Player Restarts
**Problem in v1.2.2:**
When a player restarted while soundcard was MUTED (waiting for suspend), the soundcard was not unmuted, causing no audio.

**Solution in v1.3.0:**
`activatePlayer()` now checks current state:
- If `SUSPENDED`: calls `resume()` (full resume sequence)
- If `MUTED`: calls `unmute()` (just clear mute)  ← **This fixes the bug!**
- If `ON`: no action needed

### 4. State Transitions
```
SUSPENDED  ──resume()──→  ON
    ↑                      ↓
    │                   mute()
    │                      ↓
    └────suspend()────  MUTED
                           ↑
                      unmute()
                           ↓
                          ON
```

### Implementation Details
- All GPIO operations now update the `state` field correctly
- `getStatus()` uses actual state enum instead of inferring from active players
- Separate `PowerState` enum for power supply (simpler ON/OFF model)
- Consistent naming: `resume()`/`suspend()` for major transitions, `mute()`/`unmute()` for quick toggles
- All internal references to `DeviceState.OFF` changed to `DeviceState.SUSPENDED`
- `suspend()` verifies state is MUTED before suspending (defensive check)
- `unmute()` checks if suspended and warns (prevents invalid state transitions)

### Backward Compatibility
- **Fully compatible** with existing configuration files
- **Fully compatible** with Squeezelite callback protocol
- Status JSON format unchanged (same state strings: "on", "muted", "suspended")
- Socket protocol unchanged
- Externally visible behavior identical (except bug fix)
- No changes required to monitoring tools

### Benefits
1. **Bug Fix:** Unmute works correctly when player restarts from MUTED state
2. **Clearer Code:** Method names clearly indicate what they do
3. **Better State Tracking:** State enum always reflects actual GPIO state
4. **Easier Debugging:** State is explicit in logs and status
5. **More Maintainable:** State machine logic is clearer and easier to extend

### Improvements
1. **Proper Shutdown Sequence:** Hardware is now shut down before error LED activation
   - **Before (1.2.1):** Error LED turned on first, then cleanup
   - **After (1.2.2):** Soundcards muted/suspended → Power supply off → Error LED on
   - **Reason:** Ensures clean hardware shutdown even during daemon termination
   - Prevents amplifiers staying powered if daemon crashes during shutdown

2. **Human-Readable Player Names in Status:** Status JSON now uses player description in name field
   - **Before (1.2.1):** `"name": "wohnzimmer"` (technical ID)
   - **After (1.2.2):** `"name": "Wohnzimmer"` (description from config with umlauts)
   - **Applies to:** Players section only, soundcard names remain technical IDs
   - **Reason:** Better readability in logs and monitoring dashboards (Grafana, etc.)
   - Umlauts and special characters now properly displayed for players

### Implementation Details
- `SoundcardConfig` dataclass: Changed `players` from `Set[str]` to `Dict[str, str]` (name → description mapping)
- `setupSoundcards()`: Loads player descriptions from YAML config (falls back to name if not present)
- `getStatus()`: Uses player description in `name` field of players section
- `stop()`: Reordered shutdown sequence:
  1. Mute all active soundcards (MUTE HIGH)
  2. Suspend all soundcards (SUSPEND HIGH, LED LOW)
  3. Deactivate power supply (GPIO LOW)
  4. Activate error LED (GPIO HIGH)
  5. Write final status and cleanup files

### Configuration File
- Player `description` field now used in status output
- Example:
  ```yaml
  soundcards:
    - id: 1
      name: KAB9_1
      players:
        - name: wohnzimmer          # Technical ID (used as key)
          description: "Wohnzimmer" # Human-readable (used in status JSON name field)
        - name: kueche
          description: "Küche"      # With umlauts
  ```
- If player `description` not provided, `name` is used as fallback (backward compatible)

### Backward Compatibility
- **Fully backward compatible** with configuration files from v1.2.1
- Existing configs without player `description` field continue to work (uses `name` as fallback)
- Status JSON format unchanged (same structure, different values in players.name)
- Socket protocol unchanged
- Monitoring tools may need adjustment if they rely on exact player name matching in displays
