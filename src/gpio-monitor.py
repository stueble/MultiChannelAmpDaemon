#!/usr/bin/env python3
"""
GPIO Monitor for Raspberry Pi 5
Outputs GPIO states in InfluxDB line protocol format for Telegraf

Version: 1.0.0
"""

import sys
import time
import argparse
from typing import Dict, List

# GPIO configuration - can be loaded from config file
DEFAULT_GPIOS = {
    # Power Supply
    'power_supply': {
        'pin': 13,
        'description': 'Main power supply control',
        'inverted': True  # HIGH=OFF, LOW=ON
    },

    # Error LED
    'error_led': {
        'pin': 26,
        'description': 'Error LED indicator'
    },

    # Soundcard 1 (KAB9_1)
    'soundcard1_suspend': {
        'pin': 12,
        'description': 'KAB9_1 SUSPEND control',
        'inverted': True  # HIGH=suspended, LOW=active
    },
    'soundcard1_mute': {
        'pin': 16,
        'description': 'KAB9_1 MUTE control',
        'inverted': True  # HIGH=muted, LOW=unmuted
    },
    'soundcard1_led': {
        'pin': 17,
        'description': 'KAB9_1 status LED'
    },

    # Soundcard 2 (KAB9_2)
    'soundcard2_suspend': {
        'pin': 6,
        'description': 'KAB9_2 SUSPEND control',
        'inverted': True
    },
    'soundcard2_mute': {
        'pin': 25,
        'description': 'KAB9_2 MUTE control',
        'inverted': True
    },
    'soundcard2_led': {
        'pin': 27,
        'description': 'KAB9_2 status LED'
    },

    # Soundcard 3 (KAB9_3)
    'soundcard3_suspend': {
        'pin': 23,
        'description': 'KAB9_3 SUSPEND control',
        'inverted': True
    },
    'soundcard3_mute': {
        'pin': 24,
        'description': 'KAB9_3 MUTE control',
        'inverted': True
    },
    'soundcard3_led': {
        'pin': 22,
        'description': 'KAB9_3 status LED'
    }
}


class GpioReader:
    """Reads GPIO states from sysfs"""

    def __init__(self, gpioConfigs: Dict):
        self.gpioConfigs = gpioConfigs
        self.useSysfs = True

        # Try to use RPi.GPIO first, fall back to sysfs
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            self.GPIO = GPIO
            self.useSysfs = False
        except (ImportError, RuntimeError):
            # Fall back to sysfs reading
            self.useSysfs = True

    def readGpioSysfs(self, pin: int) -> int:
        """Read GPIO value via sysfs"""
        try:
            with open(f'/sys/class/gpio/gpio{pin}/value', 'r') as f:
                return int(f.read().strip())
        except FileNotFoundError:
            # GPIO not exported, try to export it
            try:
                with open('/sys/class/gpio/export', 'w') as f:
                    f.write(str(pin))
                time.sleep(0.1)
                with open(f'/sys/class/gpio/gpio{pin}/value', 'r') as f:
                    return int(f.read().strip())
            except:
                return -1
        except:
            return -1

    def readGpioRpi(self, pin: int) -> int:
        """Read GPIO value via RPi.GPIO"""
        try:
            self.GPIO.setup(pin, self.GPIO.IN)
            return self.GPIO.input(pin)
        except:
            return -1

    def readGpio(self, pin: int) -> int:
        """Read GPIO value (0, 1, or -1 for error)"""
        if self.useSysfs:
            return self.readGpioSysfs(pin)
        else:
            return self.readGpioRpi(pin)

    def readAllGpios(self) -> Dict[str, Dict]:
        """Read all configured GPIOs"""
        results = {}

        for name, config in self.gpioConfigs.items():
            pin = config['pin']
            rawValue = self.readGpio(pin)

            # Apply inversion if configured
            if config.get('inverted', False) and rawValue != -1:
                value = 1 - rawValue
            else:
                value = rawValue

            results[name] = {
                'pin': pin,
                'raw_value': rawValue,
                'value': value,
                'description': config.get('description', ''),
                'error': rawValue == -1
            }

        return results


class TelegrafFormatter:
    """Formats GPIO data for Telegraf (InfluxDB line protocol)"""

    def __init__(self, measurement: str = "gpio"):
        self.measurement = measurement

    def formatLineProtocol(self, gpioData: Dict[str, Dict], timestamp: int = None) -> List[str]:
        """
        Format GPIO data in InfluxDB line protocol

        Format: measurement,tag1=value1,tag2=value2 field1=value1,field2=value2 timestamp
        """
        lines = []

        for name, data in gpioData.items():
            if data['error']:
                continue

            # Tags (indexed fields)
            tags = [
                f"gpio_name={name}",
                f"pin={data['pin']}"
            ]
            tagsStr = ','.join(tags)

            # Fields (data values)
            fields = [
                f"value={data['value']}i",
                f"raw_value={data['raw_value']}i"
            ]
            fieldsStr = ','.join(fields)

            # Build line
            line = f"{self.measurement},{tagsStr} {fieldsStr}"

            # Add timestamp if provided (nanoseconds)
            if timestamp:
                line += f" {timestamp}"

            lines.append(line)

        return lines

    def formatJson(self, gpioData: Dict[str, Dict]) -> str:
        """Format GPIO data as JSON"""
        import json
        return json.dumps(gpioData, indent=2)

    def formatPrometheus(self, gpioData: Dict[str, Dict]) -> List[str]:
        """Format GPIO data in Prometheus format"""
        lines = []

        # Add HELP and TYPE for each metric
        lines.append('# HELP gpio_value GPIO pin value (0 or 1)')
        lines.append('# TYPE gpio_value gauge')

        for name, data in gpioData.items():
            if data['error']:
                continue

            # Prometheus format: metric_name{label1="value1",label2="value2"} value
            labels = f'gpio_name="{name}",pin="{data["pin"]}",description="{data["description"]}"'
            lines.append(f'gpio_value{{{labels}}} {data["value"]}')

        return lines

    def formatHuman(self, gpioData: Dict[str, Dict]) -> str:
        """Format GPIO data in human-readable format"""
        lines = []
        lines.append("GPIO Status:")
        lines.append("=" * 80)

        for name, data in gpioData.items():
            if data['error']:
                status = "ERROR"
                value = "N/A"
            else:
                value = data['value']
                status = "ON" if value == 1 else "OFF"

            lines.append(f"{name:25} (GPIO {data['pin']:2d}): {status:5} [{value}]  {data['description']}")

        return '\n'.join(lines)


def loadConfigFromYaml(yamlPath: str) -> Dict:
    """Load GPIO configuration from MultiChannelAmpDaemon YAML"""
    try:
        import yaml
        with open(yamlPath, 'r') as f:
            config = yaml.safe_load(f)

        gpioConfigs = {}

        # Extract global GPIOs
        globalConfig = config.get('global', {})
        if 'gpio_power_supply' in globalConfig:
            gpioConfigs['power_supply'] = {
                'pin': globalConfig['gpio_power_supply'],
                'description': 'Main power supply control',
                'inverted': True
            }

        if 'gpio_error_led' in globalConfig:
            gpioConfigs['error_led'] = {
                'pin': globalConfig['gpio_error_led'],
                'description': 'Error LED indicator'
            }

        # Extract soundcard GPIOs
        for soundcard in config.get('soundcards', []):
            scId = soundcard['id']
            scName = soundcard['name']
            gpio = soundcard.get('gpio', {})

            if 'suspend' in gpio:
                gpioConfigs[f'soundcard{scId}_suspend'] = {
                    'pin': gpio['suspend'],
                    'description': f'{scName} SUSPEND control',
                    'inverted': True
                }

            if 'mute' in gpio:
                gpioConfigs[f'soundcard{scId}_mute'] = {
                    'pin': gpio['mute'],
                    'description': f'{scName} MUTE control',
                    'inverted': True
                }

            if 'led' in gpio:
                gpioConfigs[f'soundcard{scId}_led'] = {
                    'pin': gpio['led'],
                    'description': f'{scName} status LED'
                }

        return gpioConfigs

    except Exception as e:
        print(f"Error loading config from {yamlPath}: {e}", file=sys.stderr)
        return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='GPIO Monitor for Raspberry Pi - Telegraf compatible output',
        epilog='Version 1.0.0'
    )

    parser.add_argument(
        '--format', '-f',
        choices=['influx', 'json', 'prometheus', 'human'],
        default='influx',
        help='Output format (default: influx)'
    )

    parser.add_argument(
        '--config', '-c',
        help='Load GPIO configuration from MultiChannelAmpDaemon YAML file'
    )

    parser.add_argument(
        '--measurement', '-m',
        default='gpio',
        help='Measurement name for InfluxDB line protocol (default: gpio)'
    )

    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Continuous monitoring mode (output every second)'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=1,
        help='Interval in seconds for continuous mode (default: 1)'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )

    args = parser.parse_args()

    # Load GPIO configuration
    if args.config:
        gpioConfigs = loadConfigFromYaml(args.config)
        if not gpioConfigs:
            print("Failed to load configuration, using defaults", file=sys.stderr)
            gpioConfigs = DEFAULT_GPIOS
    else:
        gpioConfigs = DEFAULT_GPIOS

    # Initialize reader and formatter
    reader = GpioReader(gpioConfigs)
    formatter = TelegrafFormatter(measurement=args.measurement)

    # Single read or continuous monitoring
    try:
        if args.continuous:
            while True:
                gpioData = reader.readAllGpios()

                if args.format == 'influx':
                    timestamp = int(time.time() * 1e9)  # nanoseconds
                    for line in formatter.formatLineProtocol(gpioData, timestamp):
                        print(line)
                elif args.format == 'json':
                    print(formatter.formatJson(gpioData))
                elif args.format == 'prometheus':
                    for line in formatter.formatPrometheus(gpioData):
                        print(line)
                else:  # human
                    print(formatter.formatHuman(gpioData))
                    print()

                sys.stdout.flush()
                time.sleep(args.interval)
        else:
            # Single read
            gpioData = reader.readAllGpios()

            if args.format == 'influx':
                for line in formatter.formatLineProtocol(gpioData):
                    print(line)
            elif args.format == 'json':
                print(formatter.formatJson(gpioData))
            elif args.format == 'prometheus':
                for line in formatter.formatPrometheus(gpioData):
                    print(line)
            else:  # human
                print(formatter.formatHuman(gpioData))

    except KeyboardInterrupt:
        print("\nMonitoring stopped", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
