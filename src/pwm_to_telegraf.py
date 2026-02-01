#!/usr/bin/env python3

# Adapt path if neccessary
duty_path = "/sys/class/pwm/pwmchip0/pwm2/duty_cycle"
# I hardcoded period to 40000
# period_path = "/sys/class/pwm/pwmchip0/pwm2/period"

# Werte auslesen
with open(duty_path, "r") as f:
    duty = int(f.read().strip())

# with open(period_path, "r") as f:
#    period = int(f.read().strip())

# Prozentwert berechnen
percent = round((duty / 40000) * 100, 1)

# Ausgabe im Telegraf Line Protocol
print(f"raspberrypi_pwm,duty=fan value={percent}")
