#!/usr/bin/env python3
"""
PWM Fan Control Daemon for Raspberry Pi 5
Controls a 2-wire PWM fan based on DS18B20 temperature sensor readings.
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path
from typing import Optional

# Configuration
CONFIG = {
    'sensor_ids': ['28-00000034e4f3', '28-00000050cf0c', '28-00000034e4f3'],  # List of sensor IDs
    'sensor_path': '/sys/bus/w1/devices/{}/w1_slave',
    'pwm_chip': '/sys/class/pwm/pwmchip0',
    'pwm_channel': 2,
    'gpio_pin': 18,

    # PWM settings (25 kHz)
    'pwm_period': 40000,  # nanoseconds (1/25000 Hz)
    'pwm_min': 10000,     # 25% - minimum to start fan
    'pwm_max': 40000,     # 100% - maximum
    'pwm_shutdown': 20000, # 50% - value on daemon shutdown

    # Temperature control
    'temp_min': 40.0,     # °C - fan starts
    'temp_max': 60.0,     # °C - fan at 100%
    'temp_hysteresis': 2.0,  # °C - hysteresis to prevent oscillation
    'update_interval': 20, # seconds

    # Error handling
    'sensor_fail_pwm': 20000,  # 50% on sensor failure
}


class PWMFanController:
    """Controls PWM fan based on temperature sensor readings."""

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.pwm_path = None
        self.current_duty = 0
        self.fan_running = False  # Track if fan is currently running for hysteresis

    def setup_logging(self):
        """Configure logging to systemd journal."""
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(levelname)s: %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )

    def read_temperature(self) -> Optional[float]:
        """Read temperature from all DS18B20 sensors and return the maximum value."""
        temperatures = []

        for sensor_id in self.config['sensor_ids']:
            sensor_file = self.config['sensor_path'].format(sensor_id)

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
                        self.logger.debug(f"Sensor {sensor_id}: {temp_c:.1f}°C")

            except FileNotFoundError:
                self.logger.warning(f"Sensor {sensor_id} not found")
            except (IOError, ValueError) as e:
                self.logger.warning(f"Error reading sensor {sensor_id}: {e}")

        if temperatures:
            # Return the maximum temperature
            max_sensor, max_temp = max(temperatures, key=lambda x: x[1])
            self.logger.debug(f"Using maximum temperature from sensor {max_sensor}")
            return max_temp

        return None

    def calculate_duty_cycle(self, temp: float) -> int:
        """Calculate PWM duty cycle based on temperature with hysteresis."""
        hysteresis = self.config['temp_hysteresis']

        # Determine effective threshold based on current fan state
        if self.fan_running:
            # Fan is running - use lower threshold (temp_min - hysteresis) to turn off
            effective_min = self.config['temp_min'] - hysteresis
        else:
            # Fan is off - use normal threshold (temp_min) to turn on
            effective_min = self.config['temp_min']

        if temp < effective_min:
            # Below minimum temperature (with hysteresis) - fan off
            self.fan_running = False
            return 0

        elif temp >= self.config['temp_max']:
            # Above maximum temperature - fan at 100%
            self.fan_running = True
            return self.config['pwm_max']

        else:
            # Linear interpolation between min and max
            # Use actual temp_min for calculation, not effective_min
            temp_range = self.config['temp_max'] - self.config['temp_min']
            temp_offset = temp - self.config['temp_min']
            temp_ratio = temp_offset / temp_range

            duty_range = self.config['pwm_max'] - self.config['pwm_min']
            duty_cycle = self.config['pwm_min'] + int(duty_range * temp_ratio)

            self.fan_running = True
            return duty_cycle

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
                f.write(str(self.config['pwm_period']))
            self.logger.info(f"Set PWM period to {self.config['pwm_period']} ns (25 kHz)")
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

    def set_duty_cycle(self, duty_cycle: int):
        """Set PWM duty cycle."""
        if self.pwm_path is None:
            self.logger.error("PWM not initialized")
            return

        duty_file = self.pwm_path / 'duty_cycle'

        # Ensure duty cycle is within valid range
        duty_cycle = max(0, min(duty_cycle, self.config['pwm_period']))

        try:
            with open(duty_file, 'w') as f:
                f.write(str(duty_cycle))

            if duty_cycle != self.current_duty:
                percent = (duty_cycle / self.config['pwm_period']) * 100
                self.logger.info(f"Set fan speed to {percent:.1f}% (duty_cycle: {duty_cycle} ns)")
                self.current_duty = duty_cycle

        except IOError as e:
            self.logger.error(f"Failed to set duty cycle: {e}")

    def cleanup_pwm(self):
        """Disable and unexport PWM."""
        if self.pwm_path is None:
            return

        # Set shutdown duty cycle
        self.logger.info("Setting shutdown duty cycle")
        self.set_duty_cycle(self.config['pwm_shutdown'])
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
        self.logger.info("PWM Fan Control Daemon starting...")
        self.logger.info(f"Sensors: {', '.join(self.config['sensor_ids'])}")
        self.logger.info(f"Temperature range: {self.config['temp_min']}°C - {self.config['temp_max']}°C")
        self.logger.info(f"Hysteresis: {self.config['temp_hysteresis']}°C")
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
        consecutive_errors = 0
        max_consecutive_errors = 3

        try:
            while self.running:
                temp = self.read_temperature()

                if temp is not None:
                    consecutive_errors = 0
                    duty_cycle = self.calculate_duty_cycle(temp)
                    self.logger.info(f"Temperature: {temp:.1f}°C")
                    self.set_duty_cycle(duty_cycle)

                else:
                    consecutive_errors += 1
                    self.logger.warning(f"Failed to read temperature (attempt {consecutive_errors}/{max_consecutive_errors})")

                    if consecutive_errors >= max_consecutive_errors:
                        self.logger.error("Sensor failure detected - setting fan to 50%")
                        self.set_duty_cycle(self.config['sensor_fail_pwm'])

                # Wait for next update
                time.sleep(self.config['update_interval'])

        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
            return 1

        finally:
            self.cleanup_pwm()

        self.logger.info("PWM Fan Control Daemon stopped")
        return 0


def main():
    """Entry point for the daemon."""
    controller = PWMFanController(CONFIG)
    return controller.run()


if __name__ == '__main__':
    sys.exit(main())
