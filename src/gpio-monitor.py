#!/usr/bin/env python3
"""
GPIO Monitor using pinctrl
Works even when GPIOs are claimed by other processes

Version: 1.0.0
"""

import sys
import re
import time
import argparse
import subprocess
from typing import Dict, Optional

# GPIO mapping
GPIO_MAP = {
    'power_supply': {'pin': 13, 'inverted': True, 'desc': 'Power supply'},
    'error_led': {'pin': 26, 'inverted': False, 'desc': 'Error LED'},
    'sc1_suspend': {'pin': 12, 'inverted': True, 'desc': 'KAB9_1 suspend'},
    'sc1_mute': {'pin': 16, 'inverted': True, 'desc': 'KAB9_1 mute'},
    'sc1_led': {'pin': 17, 'inverted': False, 'desc': 'KAB9_1 LED'},
    'sc2_suspend': {'pin': 6, 'inverted': True, 'desc': 'KAB9_2 suspend'},
    'sc2_mute': {'pin': 25, 'inverted': True, 'desc': 'KAB9_2 mute'},
    'sc2_led': {'pin': 27, 'inverted': False, 'desc': 'KAB9_2 LED'},
    'sc3_suspend': {'pin': 23, 'inverted': True, 'desc': 'KAB9_3 suspend'},
    'sc3_mute': {'pin': 24, 'inverted': True, 'desc': 'KAB9_3 mute'},
    'sc3_led': {'pin': 22, 'inverted': False, 'desc': 'KAB9_3 LED'},
}


def loadConfigFromYaml(yamlPath: str) -> Optional[Dict]:
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
                'description': 'Error LED indicator',
                'inverted': False
            }

        # Extract soundcard GPIOs
        for soundcard in config.get('soundcards', []):
            scId = soundcard['id']
            scName = soundcard['name']
            gpio = soundcard.get('gpio', {})

            if 'suspend' in gpio:
                gpioConfigs[f'sc{scId}_suspend'] = {
                    'pin': gpio['suspend'],
                    'description': f'{scName} SUSPEND',
                    'inverted': True
                }

            if 'mute' in gpio:
                gpioConfigs[f'sc{scId}_mute'] = {
                    'pin': gpio['mute'],
                    'description': f'{scName} MUTE',
                    'inverted': True
                }

            if 'led' in gpio:
                gpioConfigs[f'sc{scId}_led'] = {
                    'pin': gpio['led'],
                    'description': f'{scName} LED',
                    'inverted': False
                }

        # Convert to GPIO_MAP format
        result = {}
        for name, cfg in gpioConfigs.items():
            result[name] = {
                'pin': cfg['pin'],
                'inverted': cfg.get('inverted', False),
                'desc': cfg['description']
            }

        return result

    except Exception as e:
        print(f"Error loading config from {yamlPath}: {e}", file=sys.stderr)
        return None


def runPinctrl() -> Optional[str]:
    """Run pinctrl get command to get GPIO states"""
    try:
        result = subprocess.run(
            ['pinctrl', 'get'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return result.stdout
        else:
            print(f"Error running pinctrl: {result.stderr}", file=sys.stderr)
            return None

    except FileNotFoundError:
        print("ERROR: pinctrl command not found", file=sys.stderr)
        print("Install with: sudo apt install pinctrl", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("ERROR: pinctrl command timed out", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def parsePinctrlOutput(output: str, gpioMap: Dict) -> Dict:
    """Parse pinctrl output to extract GPIO states"""
    results = {}

    # Build a set of pins we're interested in
    pinsOfInterest = {config['pin'] for config in gpioMap.values()}

    # Parse pinctrl output
    # Format example:
    # 12: ip    -- | hi // GPIO12 = none
    # 13: op dh -- | hi // GPIO13 = none

    for line in output.split('\n'):
        # Match pattern like "12: op dh -- | hi // GPIO12"
        match = re.match(r'^\s*(\d+):\s+(\w+)\s+.*?\|\s+(hi|lo)\s+//', line)
        if match:
            pin = int(match.group(1))
            direction = match.group(2)  # ip=input, op=output
            level = match.group(3)  # hi or lo

            if pin in pinsOfInterest:
                rawValue = 1 if level == 'hi' else 0

                # Find the corresponding config
                for name, config in gpioMap.items():
                    if config['pin'] == pin:
                        # Apply inversion
                        if config['inverted']:
                            value = 1 - rawValue
                        else:
                            value = rawValue

                        results[name] = {
                            'pin': pin,
                            'raw_value': rawValue,
                            'value': value,
                            'direction': 'in' if direction == 'ip' else 'out',
                            'description': config['desc'],
                            'error': False
                        }
                        break

    # Add missing GPIOs as errors
    for name, config in gpioMap.items():
        if name not in results:
            results[name] = {
                'pin': config['pin'],
                'raw_value': -1,
                'value': -1,
                'direction': 'unknown',
                'description': config['desc'],
                'error': True
            }

    return results


def readAllGpios(gpioMap: Dict) -> Optional[Dict]:
    """Read all configured GPIOs using pinctrl"""
    output = runPinctrl()
    if output is None:
        return None

    return parsePinctrlOutput(output, gpioMap)


def formatInflux(data: Dict, measurement: str = 'gpio') -> str:
    """Format as InfluxDB line protocol"""
    lines = []
    timestamp = int(time.time() * 1e9)

    for name, gpio in data.items():
        if gpio['error']:
            continue

        tags = f"gpio_name={name},pin={gpio['pin']},direction={gpio['direction']}"
        fields = f"value={gpio['value']}i,raw_value={gpio['raw_value']}i"
        lines.append(f"{measurement},{tags} {fields} {timestamp}")

    return '\n'.join(lines)


def formatHuman(data: Dict) -> str:
    """Format human-readable"""
    lines = []
    lines.append("GPIO Status (via pinctrl):")
    lines.append("=" * 90)

    errorCount = 0
    for name, gpio in data.items():
        if gpio['error']:
            status = "ERROR"
            extra = ""
            errorCount += 1
        else:
            status = "ON " if gpio['value'] == 1 else "OFF"
            extra = f"[{gpio['direction']:3s}, raw={gpio['raw_value']}]"

        lines.append(f"{name:20} GPIO{gpio['pin']:3d}: {status:5s} {extra:15s} {gpio['description']}")

    if errorCount > 0:
        lines.append("")
        lines.append(f"⚠ {errorCount} GPIO(s) could not be read")

    return '\n'.join(lines)


def formatJson(data: Dict) -> str:
    """Format as JSON"""
    import json
    return json.dumps(data, indent=2)


def formatPrometheus(data: Dict) -> str:
    """Format as Prometheus metrics"""
    lines = []
    lines.append('# HELP gpio_value GPIO pin value (0 or 1)')
    lines.append('# TYPE gpio_value gauge')

    for name, gpio in data.items():
        if gpio['error']:
            continue

        labels = f'gpio_name="{name}",pin="{gpio["pin"]}",direction="{gpio["direction"]}",description="{gpio["description"]}"'
        lines.append(f'gpio_value{{{labels}}} {gpio["value"]}')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='GPIO Monitor using pinctrl - works with claimed GPIOs',
        epilog='Version 1.0.0'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['influx', 'human', 'json', 'prometheus'],
        default='human',
        help='Output format (default: human)'
    )
    parser.add_argument(
        '--config', '-c',
        help='Load GPIO configuration from MultiChannelAmpDaemon YAML file'
    )
    parser.add_argument(
        '--measurement', '-m',
        default='gpio',
        help='Measurement name for InfluxDB (default: gpio)'
    )
    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Continuous monitoring'
    )
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=1,
        help='Update interval in seconds (default: 1)'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )

    args = parser.parse_args()

    # Load GPIO map
    if args.config:
        gpioMap = loadConfigFromYaml(args.config)
        if gpioMap is None:
            print("Using default GPIO mapping", file=sys.stderr)
            gpioMap = GPIO_MAP
    else:
        gpioMap = GPIO_MAP

    try:
        while True:
            data = readAllGpios(gpioMap)
            if data is None:
                sys.exit(1)

            if args.format == 'influx':
                print(formatInflux(data, args.measurement))
            elif args.format == 'json':
                print(formatJson(data))
            elif args.format == 'prometheus':
                print(formatPrometheus(data))
            else:  # human
                print(formatHuman(data))

            if not args.continuous:
                break

            if args.format == 'human':
                print()  # Empty line between updates

            sys.stdout.flush()
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped", file=sys.stderr)


if __name__ == '__main__':
    main()
