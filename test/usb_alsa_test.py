#!/usr/bin/env python3
"""
Test script for USB/ALSA suspend and resume functionality
Tests the deactivation and reactivation of USB audio devices
"""

import subprocess
import time
import sys
import os

# Configuration - adjust to your sound cards
TEST_DEVICES = [
    {
        "name": "KAB9_1",
        "alsa_card": "4",  # Card number from 'aplay -l'
        "usb_device": "1-2"  # USB device path from 'lsusb -t' or /sys/bus/usb/devices/
    },
    {
        "name": "KAB9_2",
        "alsa_card": "3",
        "usb_device": "3-1"
    },
    {
        "name": "KAB9_3",
        "alsa_card": "0",
        "usb_device": "1-1"
    }
]

DELAY = 2  # Seconds between operations


def runCommand(cmd, description, ignoreError=False):
    """Runs a shell command and prints the result"""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    print('-'*60)

    try:
        if isinstance(cmd, str):
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

        if result.stdout:
            print(f"Output: {result.stdout}")
        if result.stderr:
            print(f"Stderr: {result.stderr}")

        if result.returncode != 0 and not ignoreError:
            print(f"❌ Command failed with return code {result.returncode}")
            return False
        else:
            print(f"✅ Success (return code: {result.returncode})")
            return True

    except subprocess.TimeoutExpired:
        print("❌ Command timed out")
        return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def checkAlsaCard(cardNumber):
    """Checks if ALSA card exists and shows info"""
    print(f"\n{'='*60}")
    print(f"Checking ALSA card {cardNumber}")
    print('-'*60)

    # Check card info
    runCommand(
        ['cat', f'/proc/asound/card{cardNumber}/id'],
        f"Get card {cardNumber} ID",
        ignoreError=True
    )

    # Check if card is in use
    runCommand(
        ['fuser', '-v', f'/dev/snd/controlC{cardNumber}'],
        f"Check if card {cardNumber} is in use",
        ignoreError=True
    )


def checkUsbDevice(usbDevice):
    """Checks USB device status"""
    powerPath = f'/sys/bus/usb/devices/{usbDevice}/power/level'
    controlPath = f'/sys/bus/usb/devices/{usbDevice}/power/control'

    print(f"\n{'='*60}")
    print(f"Checking USB device {usbDevice}")
    print('-'*60)

    if os.path.exists(powerPath):
        runCommand(
            ['cat', powerPath],
            f"Current power level of {usbDevice}",
            ignoreError=True
        )
    else:
        print(f"⚠️  Power level path not found: {powerPath}")

    if os.path.exists(controlPath):
        runCommand(
            ['cat', controlPath],
            f"Current power control of {usbDevice}",
            ignoreError=True
        )
    else:
        print(f"⚠️  Control path not found: {controlPath}")


def suspendAlsa(cardNumber):
    """Suspends ALSA card"""
    print(f"\n{'#'*60}")
    print(f"# SUSPENDING ALSA CARD {cardNumber}")
    print(f"{'#'*60}")

    # Store ALSA state
    success = runCommand(
        ['sudo', 'alsactl', 'store', str(cardNumber)],
        f"Store ALSA state for card {cardNumber}"
    )

    return success


def resumeAlsa(cardNumber):
    """Resumes ALSA card"""
    print(f"\n{'#'*60}")
    print(f"# RESUMING ALSA CARD {cardNumber}")
    print(f"{'#'*60}")

    # Restore ALSA state
    success = runCommand(
        ['sudo', 'alsactl', 'restore', str(cardNumber)],
        f"Restore ALSA state for card {cardNumber}"
    )

    return success


def suspendUsb(usbDevice):
    """Suspends USB device"""
    print(f"\n{'#'*60}")
    print(f"# SUSPENDING USB DEVICE {usbDevice}")
    print(f"{'#'*60}")

    # Method 1: Set autosuspend_delay_ms to 0 and control to auto
    autosuspendPath = f'/sys/bus/usb/devices/{usbDevice}/power/autosuspend_delay_ms'
    controlPath = f'/sys/bus/usb/devices/{usbDevice}/power/control'

    if os.path.exists(autosuspendPath) and os.path.exists(controlPath):
        # Set autosuspend delay to 0 (immediate)
        success1 = runCommand(
            f'echo "0" | sudo tee {autosuspendPath}',
            f"Set autosuspend delay to 0 for {usbDevice}"
        )

        # Enable autosuspend
        success2 = runCommand(
            f'echo "auto" | sudo tee {controlPath}',
            f"Enable autosuspend for {usbDevice}"
        )

        if success1 and success2:
            print("✅ USB device should autosuspend now")
            return True

    # Method 2: Try to find and unbind the audio driver
    print("\nTrying to unbind audio driver...")

    # Find the interface that has the audio driver
    devicePath = f'/sys/bus/usb/devices/{usbDevice}'
    if os.path.exists(devicePath):
        # Look for subdirectories like 1-2:1.0, 1-2:1.1, etc.
        result = subprocess.run(
            f'ls -d {devicePath}/*:* 2>/dev/null',
            shell=True,
            capture_output=True,
            text=True
        )

        if result.stdout:
            interfaces = result.stdout.strip().split('\n')
            for interface in interfaces:
                interfaceName = os.path.basename(interface)
                driverPath = f'{interface}/driver'

                if os.path.exists(driverPath):
                    # Get driver name
                    driverName = os.path.basename(os.readlink(driverPath))
                    print(f"Found driver '{driverName}' for interface {interfaceName}")

                    # Try to unbind
                    unbindPath = f'/sys/bus/usb/drivers/{driverName}/unbind'
                    if os.path.exists(unbindPath):
                        success = runCommand(
                            f'echo "{interfaceName}" | sudo tee {unbindPath}',
                            f"Unbind interface {interfaceName} from driver {driverName}",
                            ignoreError=True
                        )
                        if success:
                            return True

    # Method 3: Authorize = 0 (deauthorize device)
    authorizePath = f'/sys/bus/usb/devices/{usbDevice}/authorized'
    if os.path.exists(authorizePath):
        success = runCommand(
            f'echo "0" | sudo tee {authorizePath}',
            f"Deauthorize USB device {usbDevice}"
        )
        if success:
            return True

    print(f"⚠️  Could not find suitable method to suspend {usbDevice}")
    return False


def resumeUsb(usbDevice):
    """Resumes USB device"""
    print(f"\n{'#'*60}")
    print(f"# RESUMING USB DEVICE {usbDevice}")
    print(f"{'#'*60}")

    # Method 1: Set power/control to on
    controlPath = f'/sys/bus/usb/devices/{usbDevice}/power/control'
    if os.path.exists(controlPath):
        success = runCommand(
            f'echo "on" | sudo tee {controlPath}',
            f"Set USB device {usbDevice} to always-on"
        )
        if success:
            return True

    # Method 2: Re-authorize device
    authorizePath = f'/sys/bus/usb/devices/{usbDevice}/authorized'
    if os.path.exists(authorizePath):
        # First check if it's deauthorized
        result = subprocess.run(
            ['cat', authorizePath],
            capture_output=True,
            text=True
        )
        if result.stdout.strip() == '0':
            success = runCommand(
                f'echo "1" | sudo tee {authorizePath}',
                f"Re-authorize USB device {usbDevice}"
            )
            if success:
                time.sleep(2)  # Wait for device to re-enumerate
                return True

    # Method 3: Rebind driver
    devicePath = f'/sys/bus/usb/devices/{usbDevice}'
    if os.path.exists(devicePath):
        result = subprocess.run(
            f'ls -d {devicePath}/*:* 2>/dev/null',
            shell=True,
            capture_output=True,
            text=True
        )

        if result.stdout:
            interfaces = result.stdout.strip().split('\n')
            for interface in interfaces:
                interfaceName = os.path.basename(interface)

                # Try common audio drivers
                for driver in ['snd-usb-audio', 'snd_usb_audio', 'usbhid']:
                    bindPath = f'/sys/bus/usb/drivers/{driver}/bind'
                    if os.path.exists(bindPath):
                        success = runCommand(
                            f'echo "{interfaceName}" | sudo tee {bindPath}',
                            f"Rebind interface {interfaceName} to driver {driver}",
                            ignoreError=True
                        )
                        if success:
                            time.sleep(1)
                            return True

    print(f"⚠️  Could not find suitable method to resume {usbDevice}")
    return False


def testDevice(device):
    """Tests suspend/resume cycle for a device"""
    print(f"\n\n{'*'*60}")
    print(f"* TESTING DEVICE: {device['name']}")
    print(f"*   ALSA Card: {device['alsa_card']}")
    print(f"*   USB Device: {device['usb_device']}")
    print(f"{'*'*60}\n")

    # Initial status
    print("\n--- INITIAL STATUS ---")
    checkAlsaCard(device['alsa_card'])
    checkUsbDevice(device['usb_device'])

    print(f"\n⏰ Waiting {DELAY} seconds...")
    time.sleep(DELAY)

    # Suspend
    print("\n--- SUSPEND SEQUENCE ---")
    suspendAlsa(device['alsa_card'])
    time.sleep(1)
    suspendUsb(device['usb_device'])

    print(f"\n⏰ Waiting {DELAY} seconds...")
    time.sleep(DELAY)

    # Check suspended status
    print("\n--- SUSPENDED STATUS ---")
    checkAlsaCard(device['alsa_card'])
    checkUsbDevice(device['usb_device'])

    print(f"\n⏰ Waiting {DELAY} seconds...")
    time.sleep(DELAY)

    # Resume
    print("\n--- RESUME SEQUENCE ---")
    resumeUsb(device['usb_device'])
    time.sleep(1)
    resumeAlsa(device['alsa_card'])

    print(f"\n⏰ Waiting {DELAY} seconds...")
    time.sleep(DELAY)

    # Check resumed status
    print("\n--- RESUMED STATUS ---")
    checkAlsaCard(device['alsa_card'])
    checkUsbDevice(device['usb_device'])

    print(f"\n✅ Test completed for {device['name']}\n")


def findUsbDevices():
    """Lists all USB audio devices to help find correct device paths"""
    print(f"\n{'='*60}")
    print("USB AUDIO DEVICES DETECTION")
    print(f"{'='*60}\n")

    print("USB device tree:")
    runCommand(['lsusb', '-t'], "List USB device tree")

    print("\n\nAudio devices:")
    runCommand(['lsusb'], "List USB devices", ignoreError=True)

    print("\n\nALSA cards:")
    runCommand(['aplay', '-l'], "List ALSA playback devices", ignoreError=True)

    print("\n\nAvailable USB device paths:")
    runCommand(['ls', '-la', '/sys/bus/usb/devices/'], "List USB device paths")


def main():
    """Main test function"""
    print("="*60)
    print("USB/ALSA SUSPEND/RESUME TEST SCRIPT")
    print("="*60)

    if len(sys.argv) > 1 and sys.argv[1] == '--detect':
        findUsbDevices()
        return

    print("\nThis script will test suspend/resume for configured devices.")
    print("Make sure you have configured the correct ALSA card numbers")
    print("and USB device paths in the TEST_DEVICES list.\n")
    print("Run with --detect to find your devices first.\n")

    response = input("Continue with test? (y/n): ")
    if response.lower() != 'y':
        print("Test cancelled.")
        return

    # Test each device
    for device in TEST_DEVICES:
        try:
            testDevice(device)
        except KeyboardInterrupt:
            print("\n\n⚠️  Test interrupted by user")
            break
        except Exception as e:
            print(f"\n\n❌ Error testing {device['name']}: {e}")
            continue

    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


if __name__ == "__main__":
    main()
