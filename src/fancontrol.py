#!/usr/bin/env python3
"""
PWM Fan Control Daemon for Raspberry Pi 5
Controls a 2-wire PWM fan based on dual temperature sources:
- Raspberry Pi SoC and CPU Core temperatures (max of both, 50-75°C range)
- External DS18B20 sensors (soundcard amplifiers, max of all, 40-60°C range)
Fan speed = max(rpi_duty_cycle, external_duty_cycle)

Version: 1.1.0
"""

import os
import sys
import time
import signal
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Version
VERSION = "1.1.0"

# Configuration
CONFIG = {
    # Raspberry Pi temperature sensors
    'rpi_soc_sensor': '/sys/class/thermal/thermal_zone0/temp',  # SoC temperature
    'rpi_cpu_command': ['vcgencmd', 'measure_temp'],  # CPU core temperature

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
    'rpi_temp_min': 50.0,         # °C - fan starts at pwm_min_ns
    'rpi_temp_max': 75.0,         # °C - fan at pwm_max_ns
    'rpi_temp_hysteresis': 5.0,   # °C - prevents oscillation

    # External temperature control (DS18B20) - LINEAR interpolation
    'ext_temp_min': 40.0,         # °C - fan starts at pwm_min_ns
    'ext_temp_max': 60.0,         # °C - fan at pwm_max_ns
    'ext_temp_hysteresis': 5.0,   # °C - prevents oscillation

    # Update and safety settings
    'update_interval': 30,         # seconds
    'sensor_fail_pwm_ns': 20000,   # 50% on sensor failure
}


class PWMFanController:
    """Controls PWM fan based on dual temperature sources with separate ranges."""

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.pwm_path = None
        self.current_duty_ns = 0
        self.rpi_fan_running = False  # Track RPI fan state for hysteresis
        self.ext_fan_running = False  # Track external fan state for hysteresis

    def setup_logging(self):
        """Configure logging to systemd journal."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s: %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )

    def read_rpi_soc_temperature(self) -> Optional[float]:
        """Read Raspberry Pi SoC temperature from sysfs."""
        try:
            with open(self.config['rpi_soc_sensor'], 'r') as f:
                temp_millidegrees = int(f.read().strip())
                temp_celsius = temp_millidegrees / 1000.0
                return temp_celsius
        except (FileNotFoundError, ValueError, IOError) as e:
            self.logger.warning(f"Failed to read SoC temperature: {e}")
            return None

    def read_rpi_cpu_temperature(self) -> Optional[float]:
        """Read Raspberry Pi CPU core temperature via vcgencmd."""
        try:
            result = subprocess.run(
                self.config['rpi_cpu_command'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Output format: "temp=45.2'C"
                output = result.stdout.strip()
                if 'temp=' in output:
                    temp_str = output.split('=')[1].split("'")[0]
                    temp_celsius = float(temp_str)
                    return temp_celsius
            return None
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError, FileNotFoundError) as e:
            self.logger.warning(f"Failed to read CPU temperature via vcgencmd: {e}")
            return None

    def read_rpi_temperature(self) -> Optional[float]:
        """Read both RPI sensors and return maximum temperature."""
        soc_temp = self.read_rpi_soc_temperature()
        cpu_temp = self.read_rpi_cpu_temperature()

        temperatures = []
        if soc_temp is not None:
            temperatures.append(('SoC', soc_temp))
            self.logger.debug(f"RPI SoC: {soc_temp:.1f}°C")
        if cpu_temp is not None:
            temperatures.append(('CPU', cpu_temp))
            self.logger.debug(f"RPI CPU: {cpu_temp:.1f}°C")

        if temperatures:
            max_sensor, max_temp = max(temperatures, key=lambda x: x[1])
            self.logger.debug(f"RPI maximum from {max_sensor}: {max_temp:.1f}°C")
            return max_temp

        return None

    def read_external_temperature(self) -> Optional[float]:
        """Read all DS18B20 sensors and return maximum temperature."""
        temperatures = []

        for sensor_id in self.config['external_sensor_ids']:
            sensor_file = self.config['external_sensor_path'].format(sensor_id)

            try:
                with open(sensor_file, 'r') as f:
                    lines = f.readlines()

                # Check if reading is valid
                if lines[0].strip().endswith('YES'):
                    # Extract temperature value
                    temp_pos = lines[1].find('t=')
                    if temp_pos != -1:
                        temp_string = lines[1][temp_pos + 2:]
                        temp_c = float(temp_string) / 1000.0
                        temperatures.append((sensor_id, temp_c))
                        self.logger.debug(f"External sensor {sensor_id}: {temp_c:.1f}°C")

            except FileNotFoundError:
                self.logger.debug(f"External sensor {sensor_id} not found")
            except (IOError, ValueError) as e:
                self.logger.warning(f"Error reading external sensor {sensor_id}: {e}")

        if temperatures:
            # Return the maximum temperature
            max_sensor, max_temp = max(temperatures, key=lambda x: x[1])
            self.logger.debug(f"External maximum from sensor {max_sensor}")
            return max_temp

        return None

    def calculate_linear_duty_cycle(self, temp: float, fan_running: bool,
                                    temp_min: float, temp_max: float,
                                    hysteresis: float) -> Tuple[int, bool]:
        """
        Calculate PWM duty cycle based on temperature with linear interpolation and hysteresis.

        Args:
            temp: Current temperature in °C
            fan_running: Current fan state for hysteresis
            temp_min: Minimum temperature (fan starts)
            temp_max: Maximum temperature (fan at 100%)
            hysteresis: Hysteresis in °C

        Returns:
            Tuple of (duty_cycle_ns, new_fan_running_state)
        """
        pwm_min = self.config['pwm_min_ns']
        pwm_max = self.config['pwm_max_ns']

        # Determine effective threshold based on current fan state
        if fan_running:
            # Fan is running - use lower threshold to turn off
            effective_min = temp_min - hysteresis
        else:
            # Fan is off - use normal threshold to turn on
            effective_min = temp_min

        if temp < effective_min:
            # Below minimum temperature (with hysteresis) - fan off
            return (0, False)

        elif temp >= temp_max:
            # Above maximum temperature - fan at 100%
            return (pwm_max, True)

        else:
            # Linear interpolation between min and max
            # Use actual temp_min for calculation, not effective_min
            temp_range = temp_max - temp_min
            temp_offset = temp - temp_min
            temp_ratio = temp_offset / temp_range

            duty_range = pwm_max - pwm_min
            duty_cycle = pwm_min + int(duty_range * temp_ratio)

            return (duty_cycle, True)

    def setup_pwm(self):
        """Initialize PWM hardware."""
        pwm_chip = Path(self.config['pwm_chip'])
        channel = self.config['pwm_channel']

        # Export PWM channel if not already exported
        export_file = pwm_chip / 'export'
        pwm_channel_path = pwm_chip / f'pwm{channel}'

        if not pwm_channel_path.exists():
            try:
                with open(export_file, 'w') as f:
                    f.write(str(channel))
                time.sleep(0.1)  # Wait for export
                self.logger.info(f"Exported PWM channel {channel}")
            except IOError as e:
                self.logger.error(f"Failed to export PWM channel: {e}")
                raise

        self.pwm_path = pwm_channel_path

        # Set PWM period
        period_file = self.pwm_path / 'period'
        try:
            with open(period_file, 'w') as f:
                f.write(str(self.config['pwm_period_ns']))
            self.logger.info(f"Set PWM period to {self.config['pwm_period_ns']} ns (25 kHz)")
        except IOError as e:
            self.logger.error(f"Failed to set PWM period: {e}")
            raise

        # Enable PWM
        enable_file = self.pwm_path / 'enable'
        try:
            with open(enable_file, 'w') as f:
                f.write('1')
            self.logger.info("PWM enabled")
        except IOError as e:
            self.logger.error(f"Failed to enable PWM: {e}")
            raise

    def set_duty_cycle(self, duty_cycle_ns: int, source: str = ""):
        """Set PWM duty cycle in nanoseconds."""
        if self.pwm_path is None:
            self.logger.error("PWM not initialized")
            return

        duty_file = self.pwm_path / 'duty_cycle'

        # Ensure duty cycle is within valid range
        duty_cycle_ns = max(0, min(duty_cycle_ns, self.config['pwm_period_ns']))

        try:
            with open(duty_file, 'w') as f:
                f.write(str(duty_cycle_ns))

            if duty_cycle_ns != self.current_duty_ns:
                percent = (duty_cycle_ns / self.config['pwm_period_ns']) * 100
                source_str = f" - Source: {source}" if source else ""
                self.logger.info(f"Set fan speed to {percent:.1f}% ({duty_cycle_ns} ns){source_str}")
                self.current_duty_ns = duty_cycle_ns

        except IOError as e:
            self.logger.error(f"Failed to set duty cycle: {e}")

    def cleanup_pwm(self):
        """Disable and unexport PWM."""
        if self.pwm_path is None:
            return

        # Set shutdown duty cycle
        self.logger.info("Setting shutdown duty cycle")
        self.set_duty_cycle(self.config['pwm_shutdown_ns'], "shutdown")
        time.sleep(0.5)

        # Disable PWM
        enable_file = self.pwm_path / 'enable'
        try:
            with open(enable_file, 'w') as f:
                f.write('0')
            self.logger.info("PWM disabled")
        except IOError as e:
            self.logger.warning(f"Failed to disable PWM: {e}")

        # Unexport PWM channel
        unexport_file = Path(self.config['pwm_chip']) / 'unexport'
        try:
            with open(unexport_file, 'w') as f:
                f.write(str(self.config['pwm_channel']))
            self.logger.info(f"Unexported PWM channel {self.config['pwm_channel']}")
        except IOError as e:
            self.logger.warning(f"Failed to unexport PWM channel: {e}")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def run(self):
        """Main daemon loop."""
        self.setup_logging()
        self.logger.info("="*80)
        self.logger.info("=" + " "*78 + "=")
        self.logger.info("=  PWM FAN CONTROL DAEMON STARTING" + " "*44 + "=")
        self.logger.info(f"=  Version: {VERSION}" + " "*(80-14-len(VERSION)) + "=")
        self.logger.info("=  Control Mode: Dual-Loop (RPI + External Sensors)" + " "*28 + "=")
        self.logger.info("=" + " "*78 + "=")
        self.logger.info("="*80)
        self.logger.info(f"RPI SoC sensor: {self.config['rpi_soc_sensor']}")
        self.logger.info(f"RPI CPU sensor: vcgencmd measure_temp")
        self.logger.info(f"RPI temp range: {self.config['rpi_temp_min']}°C - {self.config['rpi_temp_max']}°C (linear)")
        self.logger.info(f"External sensors: {', '.join(self.config['external_sensor_ids'])}")
        self.logger.info(f"External temp range: {self.config['ext_temp_min']}°C - {self.config['ext_temp_max']}°C (linear)")
        self.logger.info(f"PWM range: {self.config['pwm_min_ns']}ns ({self.config['pwm_min_ns']/self.config['pwm_period_ns']*100:.1f}%) - "
                        f"{self.config['pwm_max_ns']}ns ({self.config['pwm_max_ns']/self.config['pwm_period_ns']*100:.1f}%)")
        self.logger.info(f"Hysteresis: RPI={self.config['rpi_temp_hysteresis']}°C, External={self.config['ext_temp_hysteresis']}°C")
        self.logger.info(f"Update interval: {self.config['update_interval']} seconds")

        # Register signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        # Setup PWM
        try:
            self.setup_pwm()
        except Exception as e:
            self.logger.error(f"Failed to initialize PWM: {e}")
            return 1

        # Main control loop
        self.running = True
        rpi_consecutive_errors = 0
        ext_consecutive_errors = 0
        max_consecutive_errors = 3

        try:
            while self.running:
                # Read RPI temperature (max of SoC and CPU)
                rpi_temp = self.read_rpi_temperature()

                if rpi_temp is not None:
                    rpi_consecutive_errors = 0
                    rpi_duty_ns, self.rpi_fan_running = self.calculate_linear_duty_cycle(
                        rpi_temp,
                        self.rpi_fan_running,
                        self.config['rpi_temp_min'],
                        self.config['rpi_temp_max'],
                        self.config['rpi_temp_hysteresis']
                    )
                    self.logger.info(f"RPI: {rpi_temp:.1f}°C → {rpi_duty_ns}ns "
                                   f"({rpi_duty_ns/self.config['pwm_period_ns']*100:.1f}%)")
                else:
                    rpi_consecutive_errors += 1
                    self.logger.warning(f"Failed to read RPI temperature (attempt {rpi_consecutive_errors}/{max_consecutive_errors})")

                    if rpi_consecutive_errors >= max_consecutive_errors:
                        self.logger.error("RPI sensor failure detected - using fallback PWM")
                        rpi_duty_ns = self.config['sensor_fail_pwm_ns']
                    else:
                        rpi_duty_ns = 0  # Don't use fallback immediately

                # Read external temperature (max of all DS18B20)
                ext_temp = self.read_external_temperature()

                if ext_temp is not None:
                    ext_consecutive_errors = 0
                    ext_duty_ns, self.ext_fan_running = self.calculate_linear_duty_cycle(
                        ext_temp,
                        self.ext_fan_running,
                        self.config['ext_temp_min'],
                        self.config['ext_temp_max'],
                        self.config['ext_temp_hysteresis']
                    )
                    self.logger.info(f"External: {ext_temp:.1f}°C → {ext_duty_ns}ns "
                                   f"({ext_duty_ns/self.config['pwm_period_ns']*100:.1f}%)")
                else:
                    ext_consecutive_errors += 1
                    if ext_consecutive_errors >= max_consecutive_errors:
                        self.logger.warning(f"All external sensors failed (attempt {ext_consecutive_errors})")
                    ext_duty_ns = 0  # External sensors optional, use 0 if all fail

                # Use MAXIMUM of both control loops
                final_duty_ns = max(rpi_duty_ns, ext_duty_ns)

                # Determine source for logging
                if rpi_duty_ns > 0 and ext_duty_ns > 0:
                    if rpi_duty_ns > ext_duty_ns:
                        source = "RPI"
                    elif ext_duty_ns > rpi_duty_ns:
                        source = "External"
                    else:
                        source = "Both (equal)"
                elif rpi_duty_ns > 0:
                    source = "RPI"
                elif ext_duty_ns > 0:
                    source = "External"
                else:
                    source = "None (fan off)"

                # Set fan speed
                self.set_duty_cycle(final_duty_ns, source)

                # Wait for next update
                time.sleep(self.config['update_interval'])

        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
            return 1

        finally:
            self.cleanup_pwm()

        self.logger.info("="*80)
        self.logger.info("PWM Fan Control Daemon stopped")
        self.logger.info("="*80)
        return 0


def main():
    """Entry point for the daemon."""
    controller = PWMFanController(CONFIG)
    return controller.run()


if __name__ == '__main__':
    sys.exit(main())
