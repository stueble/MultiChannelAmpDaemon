# PWM Fan Control Daemon for Raspberry Pi 5

Automatic fan control based on DS18B20 temperature sensor.

## Features

- **Hardware PWM** via GPIO18 (pwmchip0, channel 2)
- **25 kHz PWM frequency** for silent operation
- **Linear regulation** between 40°C and 60°C
- **Safety**: On sensor failure → fan at 50%
- **systemd integration** with automatic restart
- **Configurable** via Python dict

## Technical Specifications

| Parameter | Value |
|-----------|-------|
| PWM Frequency | 25 kHz (40,000 ns period) |
| Minimum Duty Cycle | 10,000 ns (25%) |
| Maximum Duty Cycle | 40,000 ns (100%) |
| Shutdown Duty Cycle | 20,000 ns (50%) |
| Temperature Range | 40°C - 60°C |
| Update Interval | 20 seconds |
| Sensor | DS18B20 (ID: 28-00000034e4f3) |

## Control Behavior

- **< 40°C**: Fan OFF (0%)
- **40°C**: Fan starts at 25% (10,000 ns)
- **40-60°C**: Linear increase to 100%
- **≥ 60°C**: Fan at 100% (40,000 ns)
- **Sensor Error**: Fan at 50% for safety

## Prerequisites

### Enable 1-Wire

Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older systems):

```bash
sudo nano /boot/firmware/config.txt
```

Add the following line:

```
dtoverlay=w1-gpio
```

Reboot:

```bash
sudo reboot
```

### Load 1-Wire Kernel Modules

```bash
sudo modprobe w1-gpio
sudo modprobe w1-therm
```

For automatic loading at boot:

```bash
echo "w1-gpio" | sudo tee -a /etc/modules
echo "w1-therm" | sudo tee -a /etc/modules
```

### Verify Sensor ID

```bash
ls /sys/bus/w1/devices/
```

You should see `28-00000034e4f3`. If a different ID appears, adjust the `sensor_id` in the script.

### Test Temperature Reading

```bash
cat /sys/bus/w1/devices/28-00000034e4f3/w1_slave
```

Output should look similar to:
```
b1 01 4b 46 7f ff 0c 10 d4 : crc=d4 YES
b1 01 4b 46 7f ff 0c 10 d4 t=27062
```

The temperature is `t=27062` → 27.062°C

## Installation

### 1. Install Daemon

```bash
# Copy script
sudo cp fancontrol.py /usr/local/bin/
sudo chmod +x /usr/local/bin/fancontrol.py

# Copy service file
sudo cp pwm-fan-control.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

### 2. Enable and Start Service

```bash
# Enable service (autostart at boot)
sudo systemctl enable pwm-fan-control.service

# Start service
sudo systemctl start pwm-fan-control.service
```

## Management

### Check Status

```bash
sudo systemctl status pwm-fan-control.service
```

### View Logs

```bash
# Live logs
sudo journalctl -u pwm-fan-control.service -f

# Logs since today
sudo journalctl -u pwm-fan-control.service --since today

# Last 50 lines
sudo journalctl -u pwm-fan-control.service -n 50
```

### Restart Service

```bash
sudo systemctl restart pwm-fan-control.service
```

### Stop Service

```bash
sudo systemctl stop pwm-fan-control.service
```

### Disable Service

```bash
sudo systemctl disable pwm-fan-control.service
```

## Configuration

Edit `/usr/local/bin/fancontrol.py` and adjust the `CONFIG` dictionary:

```python
CONFIG = {
    'sensor_id': '28-00000034e4f3',  # Your sensor ID
    'pwm_period': 40000,              # 25 kHz
    'pwm_min': 10000,                 # Minimum value (25%)
    'pwm_max': 40000,                 # Maximum value (100%)
    'pwm_shutdown': 20000,            # Shutdown value (50%)
    'temp_min': 40.0,                 # Start temperature
    'temp_max': 60.0,                 # 100% temperature
    'update_interval': 20,            # Seconds
    'sensor_fail_pwm': 20000,         # Sensor failure → 50%
}
```

After changes, restart the service:

```bash
sudo systemctl restart pwm-fan-control.service
```

## Troubleshooting

### PWM Not Working

Check if PWM chip is available:

```bash
ls -la /sys/class/pwm/
```

### Sensor Not Found

```bash
# Check kernel modules
lsmod | grep w1

# List 1-wire devices
ls /sys/bus/w1/devices/

# Sensor details
cat /sys/bus/w1/devices/28-*/w1_slave
```

### Service Won't Start

```bash
# Detailed logs
sudo journalctl -u pwm-fan-control.service -xe

# Manual test
sudo /usr/local/bin/fancontrol.py
```

### Permissions

The script requires root privileges for access to `/sys/class/pwm/` and `/sys/bus/w1/`.

## Uninstallation

```bash
# Stop and disable service
sudo systemctl stop pwm-fan-control.service
sudo systemctl disable pwm-fan-control.service

# Remove files
sudo rm /usr/local/bin/fancontrol.py
sudo rm /etc/systemd/system/pwm-fan-control.service

# Reload systemd
sudo systemctl daemon-reload
```

## Hardware Connection

### DS18B20 Temperature Sensor

```
DS18B20 Pin 1 (GND)   → Raspberry Pi GND
DS18B20 Pin 2 (DQ)    → Raspberry Pi GPIO4 (1-Wire Data) + 4.7kΩ pull-up to 3.3V
DS18B20 Pin 3 (VDD)   → Raspberry Pi 3.3V
```

### PWM Fan

```
Fan GND               → Raspberry Pi GND
Fan PWM               → Raspberry Pi GPIO18
Fan +12V              → External 12V power supply
```

**Important**: The fan requires a separate power supply! The Raspberry Pi cannot provide enough current for the fan.

## License

This script is free to use for private and commercial purposes.

## Support

For questions or issues:
1. Check logs: `sudo journalctl -u pwm-fan-control.service -f`
2. Test sensor: `cat /sys/bus/w1/devices/28-00000034e4f3/w1_slave`
3. Manual PWM test: see Troubleshooting section
