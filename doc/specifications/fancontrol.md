# PWM Fan Control Daemon - Technical Specification

## Version: 1.1.0

## Overview
A Python daemon for Raspberry Pi 5 that automatically controls a 2-wire PWM fan based on temperature readings from both Raspberry Pi internal sensors and external DS18B20 temperature sensors (soundcard amplifiers). The daemon uses hardware PWM for silent operation and provides temperature-based **linear speed control** with separate temperature ranges for each sensor group.

The fan speed is determined by the **maximum** calculated duty cycle from two independent control loops:
1. **RPI Temperature Control** - Based on max(SoC temperature, CPU Core temperature), **50-75°C range**
2. **External Temperature Control** - Based on max of all DS18B20 sensors (soundcard amplifiers), **40-60°C range**

This ensures the case fan responds appropriately to heat from both the Raspberry Pi and the amplifier system, with different sensitivity ranges for each.

## System Architecture

### Hardware Components
- **Raspberry Pi 5** running the daemon
- **Temperature Sensors:**
  - **SoC Sensor** (built-in): `/sys/class/thermal/thermal_zone0/temp`
  - **CPU Core Sensor** (built-in): Accessible via `vcgencmd measure_temp`
  - **DS18B20 Sensors** (1-wire, external): Three soundcard amplifier temperature sensors
    - Configured IDs: 28-00000050cf0c, 28-0000005152b4, 28-000000515cf7
- **2-wire PWM Case Fan**
  - Connected to GPIO 18 (PWM channel 2)
  - Requires external 12V power supply
  - Common GND with Raspberry Pi
- **PWM Hardware**
  - PWM chip: pwmchip0
  - PWM channel: 2
  - GPIO pin: 18

## Technical Specifications

### PWM Configuration
- **Frequency:** 25 kHz (40,000 ns period)
- **PWM Range:** 0-40,000 ns (0-100%)
- **Minimum Duty Cycle:** 10,000 ns (25%) - minimum to start fan
- **Maximum Duty Cycle:** 40,000 ns (100%) - full speed
- **Shutdown Duty Cycle:** 20,000 ns (50%) - set during daemon shutdown

### Temperature Control Parameters

The daemon implements **two independent control loops**, each with **different temperature ranges** and **linear interpolation**:

#### RPI Temperature Control (Raspberry Pi Internal Sensors)
- **Temperature Sources:** 
  - SoC: `/sys/class/thermal/thermal_zone0/temp`
  - CPU Core: `vcgencmd measure_temp`
  - **Uses maximum of both sensors**
- **Control Type:** Linear interpolation with hysteresis
- **Temperature Range:** **50°C (fan starts) to 75°C (fan at 100%)**
- **Hysteresis:** 5°C (fan turns off at 45°C when cooling down)
- **PWM Range:** 10,000 ns (25%) to 40,000 ns (100%)

**RPI Temperature-to-PWM Mapping:**
| Temperature | PWM (ns) | Percentage | Calculation |
|-------------|----------|------------|-------------|
| < 45°C (fan running) | 0 | 0% | Below hysteresis threshold |
| < 50°C (fan off) | 0 | 0% | Below start threshold |
| 50°C | 10,000 | 25% | Start: pwm_min |
| 55°C | 16,000 | 40% | Linear: 20% through range |
| 62.5°C | 25,000 | 62.5% | Linear: 50% through range |
| 70°C | 34,000 | 85% | Linear: 80% through range |
| 75°C | 40,000 | 100% | End: pwm_max |
| > 75°C | 40,000 | 100% | Clamped at maximum |

**Formula:**
```
temp_range = 75 - 50 = 25°C
temp_offset = current_temp - 50
temp_ratio = temp_offset / 25

duty_cycle = 10000 + (30000 * temp_ratio)

Example at 62.5°C:
temp_ratio = (62.5 - 50) / 25 = 0.5
duty_cycle = 10000 + (30000 * 0.5) = 25000 ns (62.5%)
```

#### External Temperature Control (Soundcard Amplifier Sensors)
- **Temperature Source:** DS18B20 1-wire sensors (maximum of all three)
- **Control Type:** Linear interpolation with hysteresis
- **Temperature Range:** **40°C (fan starts) to 60°C (fan at 100%)**
- **Hysteresis:** 5°C (fan turns off at 35°C when cooling down)
- **PWM Range:** 10,000 ns (25%) to 40,000 ns (100%)

**External Temperature-to-PWM Mapping:**
| Temperature | PWM (ns) | Percentage | Calculation |
|-------------|----------|------------|-------------|
| < 35°C (fan running) | 0 | 0% | Below hysteresis threshold |
| < 40°C (fan off) | 0 | 0% | Below start threshold |
| 40°C | 10,000 | 25% | Start: pwm_min |
| 45°C | 17,500 | 43.75% | Linear: 25% through range |
| 50°C | 25,000 | 62.5% | Linear: 50% through range |
| 55°C | 32,500 | 81.25% | Linear: 75% through range |
| 60°C | 40,000 | 100% | End: pwm_max |
| > 60°C | 40,000 | 100% | Clamped at maximum |

**Formula:**
```
temp_range = 60 - 40 = 20°C
temp_offset = current_temp - 40
temp_ratio = temp_offset / 20

duty_cycle = 10000 + (30000 * temp_ratio)

Example at 50°C:
temp_ratio = (50 - 40) / 20 = 0.5
duty_cycle = 10000 + (30000 * 0.5) = 25000 ns (62.5%)
```

### Dual-Loop Control Logic

The daemon calculates the required PWM value from both control loops and uses the **maximum**:

```
# Read RPI sensors
soc_temp = read_soc_temperature()
cpu_temp = read_cpu_temperature()
rpi_temp = max(soc_temp, cpu_temp)

# Calculate RPI duty cycle (50-75°C linear)
rpi_duty_ns = calculate_linear_duty_cycle(
    rpi_temp, 
    rpi_fan_running,
    temp_min=50.0,
    temp_max=75.0,
    hysteresis=5.0
)

# Read external sensors
ext_temp = max(ds18b20_sensor1, ds18b20_sensor2, ds18b20_sensor3)

# Calculate external duty cycle (40-60°C linear)
ext_duty_ns = calculate_linear_duty_cycle(
    ext_temp,
    ext_fan_running,
    temp_min=40.0,
    temp_max=60.0,
    hysteresis=5.0
)

# Use maximum
final_duty_ns = max(rpi_duty_ns, ext_duty_ns)
set_duty_cycle(final_duty_ns)
```

### Example Scenarios

**Scenario 1: RPI hot (65°C), Amplifiers cool (42°C)**
- RPI: 65°C → (65-50)/25 = 0.6 → 10000 + (30000 * 0.6) = 28,000 ns (70%)
- External: 42°C → (42-40)/20 = 0.1 → 10000 + (30000 * 0.1) = 13,000 ns (32.5%)
- **Final: 28,000 ns (70%)** - Source: RPI

**Scenario 2: RPI cool (48°C), Amplifiers hot (55°C)**
- RPI: 48°C → 0 ns (below 50°C threshold)
- External: 55°C → (55-40)/20 = 0.75 → 10000 + (30000 * 0.75) = 32,500 ns (81.25%)
- **Final: 32,500 ns (81.25%)** - Source: External

**Scenario 3: RPI very hot (73°C), Amplifiers hot (58°C)**
- RPI: 73°C → (73-50)/25 = 0.92 → 10000 + (30000 * 0.92) = 37,600 ns (94%)
- External: 58°C → (58-40)/20 = 0.9 → 10000 + (30000 * 0.9) = 37,000 ns (92.5%)
- **Final: 37,600 ns (94%)** - Source: RPI

**Scenario 4: Both cool (RPI 46°C, External 38°C)**
- RPI: 46°C → 0 ns (below 50°C)
- External: 38°C → 0 ns (below 40°C)
- **Final: 0 ns (0%)** - Source: None (fan off)

**Scenario 5: Amplifiers at critical temp (62°C), RPI moderate (52°C)**
- RPI: 52°C → (52-50)/25 = 0.08 → 10000 + (30000 * 0.08) = 12,400 ns (31%)
- External: 62°C → 40,000 ns (above 60°C, clamped at max)
- **Final: 40,000 ns (100%)** - Source: External

### Hysteresis Logic

Each control loop has independent hysteresis to prevent rapid on/off cycling:

**RPI Control Loop:**
- Fan OFF → Fan starts when temp reaches 50°C
- Fan RUNNING → Fan stops when temp drops below 45°C (50°C - 5°C)

**External Control Loop:**
- Fan OFF → Fan starts when temp reaches 40°C
- Fan RUNNING → Fan stops when temp drops below 35°C (40°C - 5°C)

**Example with External Sensors:**
- Temperature rises: 38°C → 39°C → 40°C (fan starts at 10,000 ns) → 41°C (fan at 11,500 ns)
- Temperature drops: 41°C → 40°C → 39°C (fan still running, but duty would be negative, set to 0)
- At 38°C: Still above 35°C hysteresis, fan in "running" state, duty = 0 ns
- At 34°C: Below 35°C hysteresis threshold, fan turns OFF, state = "off"

### Raspberry Pi 5 Dual Sensor Architecture

The Raspberry Pi 5 has two independent temperature sensors:

1. **SoC (System-on-Chip) Temperature**
   - Location: `/sys/class/thermal/thermal_zone0/temp`
   - Format: Millidegrees Celsius (e.g., 45230 = 45.23°C)
   - Read method: Direct file read
   - Measures: Overall SoC temperature including GPU, memory controller

2. **CPU Core Temperature**
   - Access: `vcgencmd measure_temp`
   - Format: `temp=45.2'C`
   - Read method: Subprocess call to vcgencmd
   - Measures: CPU core temperature specifically

**Why use both?**
- CPU cores can run hotter than SoC under CPU-intensive workloads
- SoC can be hotter during GPU/memory intensive tasks
- Using maximum ensures adequate cooling regardless of workload type

## File Structure

### Main Daemon File

**File:** `fancontrol.py`

**Location:** `/usr/local/bin/fancontrol.py`

**Permissions:** 755 (executable)

**Version:** 1.1.0

### Configuration Dictionary

```python
CONFIG = {
    # Raspberry Pi temperature sensors
    'rpi_soc_sensor': '/sys/class/thermal/thermal_zone0/temp',
    'rpi_cpu_command': ['vcgencmd', 'measure_temp'],
    
    # External DS18B20 sensors (soundcard amplifiers)
    'external_sensor_ids': [
        '28-00000050cf0c',  # KAB9_1
        '28-0000005152b4',  # KAB9_2
        '28-000000515cf7'   # KAB9_3
    ],
    'external_sensor_path': '/sys/bus/w1/devices/{}/w1_slave',
    
    # PWM hardware
    'pwm_chip': '/sys/class/pwm/pwmchip0',
    'pwm_channel': 2,
    'gpio_pin': 18,
    'pwm_period_ns': 40000,  # 25 kHz
    
    # PWM range (nanoseconds)
    'pwm_min_ns': 10000,      # 25% - minimum to start fan
    'pwm_max_ns': 40000,      # 100% - maximum
    'pwm_shutdown_ns': 20000, # 50% - on daemon shutdown
    
    # RPI temperature control (CPU/SoC) - LINEAR interpolation
    'rpi_temp_min': 50.0,         # °C - fan starts
    'rpi_temp_max': 75.0,         # °C - fan at 100%
    'rpi_temp_hysteresis': 5.0,   # °C - prevents oscillation
    
    # External temperature control (DS18B20) - LINEAR interpolation
    'ext_temp_min': 40.0,         # °C - fan starts
    'ext_temp_max': 60.0,         # °C - fan at 100%
    'ext_temp_hysteresis': 5.0,   # °C - prevents oscillation
    
    # Update and safety settings
    'update_interval': 30,         # seconds
    'sensor_fail_pwm_ns': 20000,   # 50% on sensor failure
}
```

### Key Methods

**`read_rpi_soc_temperature() -> Optional[float]`**
- Reads SoC temperature from sysfs
- Converts millidegrees to Celsius
- Returns None on error

**`read_rpi_cpu_temperature() -> Optional[float]`**
- Executes `vcgencmd measure_temp`
- Parses output: `temp=45.2'C`
- Returns None on error

**`read_rpi_temperature() -> Optional[float]`**
- Calls both SoC and CPU temperature methods
- Returns **maximum** of both
- Returns None if both fail

**`read_external_temperature() -> Optional[float]`**
- Reads all DS18B20 sensors
- Validates CRC
- Returns **maximum** of all sensors
- Returns None if all fail

**`calculate_linear_duty_cycle(temp, fan_running, temp_min, temp_max, hysteresis) -> (duty_ns, new_state)`**
- Generic linear interpolation function
- Used by both RPI and external control loops
- Takes separate min/max/hysteresis parameters
- Returns duty cycle in nanoseconds and new fan state

## Configuration

### Customizing Temperature Ranges

**RPI Temperature Range** (CPU/SoC):
```python
'rpi_temp_min': 50.0,   # Fan starts at 25%
'rpi_temp_max': 75.0,   # Fan at 100%
'rpi_temp_hysteresis': 5.0,
```

For more aggressive CPU cooling:
```python
'rpi_temp_min': 45.0,   # Start earlier
'rpi_temp_max': 70.0,   # Max earlier
```

For quieter operation (CPU):
```python
'rpi_temp_min': 55.0,   # Start later
'rpi_temp_max': 80.0,   # Tolerate higher temps
```

**External Temperature Range** (Amplifiers):
```python
'ext_temp_min': 40.0,   # Fan starts at 25%
'ext_temp_max': 60.0,   # Fan at 100%
'ext_temp_hysteresis': 5.0,
```

For more aggressive amplifier cooling:
```python
'ext_temp_min': 35.0,   # Start earlier
'ext_temp_max': 55.0,   # Max earlier
```

For quieter operation (amplifiers):
```python
'ext_temp_min': 45.0,   # Start later
'ext_temp_max': 65.0,   # Tolerate higher temps
```

### Update Interval

```python
'update_interval': 30,  # seconds
```

Faster response (more CPU usage):
```python
'update_interval': 10,
```

Slower response (less CPU usage):
```python
'update_interval': 60,
```

## Logging

### Startup Banner
```
================================================================================
=                                                                              =
=  PWM FAN CONTROL DAEMON STARTING                                            =
=  Version: 1.1.0                                                             =
=  Control Mode: Dual-Loop (RPI + External Sensors)                           =
=                                                                              =
================================================================================
RPI SoC sensor: /sys/class/thermal/thermal_zone0/temp
RPI CPU sensor: vcgencmd measure_temp
RPI temp range: 50.0°C - 75.0°C (linear)
External sensors: 28-00000050cf0c, 28-0000005152b4, 28-000000515cf7
External temp range: 40.0°C - 60.0°C (linear)
PWM range: 10000ns (25.0%) - 40000ns (100.0%)
Hysteresis: RPI=5.0°C, External=5.0°C
Update interval: 30 seconds
```

### Example Log Output
```
INFO: Set PWM period to 40000 ns (25 kHz)
INFO: PWM enabled
INFO: RPI: 52.3°C → 12760ns (31.9%)
INFO: External: 45.8°C → 18700ns (46.8%)
INFO: Set fan speed to 46.8% (18700 ns) - Source: External
INFO: RPI: 68.5°C → 32100ns (80.3%)
INFO: External: 48.2°C → 22300ns (55.8%)
INFO: Set fan speed to 80.3% (32100 ns) - Source: RPI
INFO: RPI: 46.0°C → 0ns (0.0%)
INFO: External: 38.0°C → 0ns (0.0%)
INFO: Set fan speed to 0.0% (0 ns) - Source: None (fan off)
```

## Installation

```bash
# Copy daemon
sudo cp fancontrol.py /usr/local/bin/
sudo chmod +x /usr/local/bin/fancontrol.py

# Configure sensor IDs
sudo nano /usr/local/bin/fancontrol.py
# Edit 'external_sensor_ids' to match your sensors

# Copy and enable service
sudo cp fancontrol.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fancontrol.service
sudo systemctl start fancontrol.service

# Verify
sudo systemctl status fancontrol.service
sudo journalctl -u fancontrol.service -f
```

## Testing

### Monitor All Sensors
```bash
watch -n 1 '
echo "=== RPI SoC ===";
cat /sys/class/thermal/thermal_zone0/temp | awk "{printf \"%.1f°C\n\", \$1/1000}";
echo "";
echo "=== RPI CPU ===";
vcgencmd measure_temp;
echo "";
echo "=== External Sensors ===";
for sensor in /sys/bus/w1/devices/28-*/w1_slave; do
  temp=$(grep "t=" $sensor | cut -d"=" -f2);
  id=$(echo $sensor | grep -o "28-[0-9a-f]*");
  echo "$id: $(awk "BEGIN {printf \"%.1f°C\", $temp/1000}")";
done;
echo "";
echo "=== Fan PWM ===";
duty=$(cat /sys/class/pwm/pwmchip0/pwm2/duty_cycle);
period=$(cat /sys/class/pwm/pwmchip0/pwm2/period);
percent=$(awk "BEGIN {printf \"%.1f%%\", ($duty/$period)*100}");
echo "Duty: $duty ns ($percent)";
'
```

### Test RPI Control
```bash
# Create CPU load
stress-ng --cpu 4 --timeout 120s

# Watch logs
sudo journalctl -u fancontrol.service -f

# Expected: RPI temp rises, fan speed increases
```

### Test External Control
```bash
# Heat amplifiers by playing music on all zones
# Or carefully warm sensors

# Watch logs
sudo journalctl -u fancontrol.service -f

# Expected: External temp rises, fan speed increases
```

## Version History

### 1.1.0 (Current)
- **NEW:** Dual-loop temperature control with separate ranges
  - RPI: 50-75°C (CPU/SoC)
  - External: 40-60°C (amplifiers)
- **NEW:** Raspberry Pi dual sensor support
  - SoC via sysfs
  - CPU Core via vcgencmd
  - Uses maximum of both
- **CHANGED:** Independent temperature ranges per control loop
- **CHANGED:** Configuration structure with separate min/max for each loop

### 1.0.0
- Initial release
- Single temperature control
- External sensors only

## License

This software is provided as-is for private and commercial use.

## References

- [Raspberry Pi 5 Documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
- [vcgencmd Documentation](https://www.raspberrypi.com/documentation/computers/os.html#vcgencmd)
- [Linux PWM Subsystem](https://www.kernel.org/doc/Documentation/pwm.txt)
- [DS18B20 Datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/DS18B20.pdf)
