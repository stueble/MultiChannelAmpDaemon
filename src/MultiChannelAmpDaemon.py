#!/usr/bin/env python3
"""
Multi-Channel Amplifier Control Daemon
Controls power supply and sound cards based on Squeezelite activity

Version: 1.1.0
"""

import sys
import time
import threading
import logging
import signal
import socket
import os
import argparse
import yaml
from pathlib import Path
from typing import Dict, Set, Optional
from dataclasses import dataclass
from enum import Enum

# Version
VERSION = "1.1.0"

# Configuration paths
DEFAULT_CONFIG_PATH = "/etc/MultiChannelAmpDaemon.yaml"

# Configuration - will be set based on config file and debug mode
SOUNDCARD_TIMEOUT = 15 * 60  # 15 minutes in seconds (normal mode)
SOUNDCARD_MUTE_DELAY = 5  # 5 seconds delay between mute and suspend
POWER_SUPPLY_TIMEOUT = 30 * 60  # 30 minutes in seconds (normal mode)
GPIO_DELAY = 1.0  # 1 second delay between GPIO operations
GPIO_ERROR_LED = 26  # GPIO pin for error LED
GPIO_POWER_SUPPLY = 13  # GPIO pin for power supply control
STATUS_FILE = "/var/run/MultiChannelAmpDaemon.status"
STATUS_JSON_FILE = "/var/run/MultiChannelAmpDaemon.status.json"
PID_FILE = "/var/run/MultiChannelAmpDaemon.pid"
SOCKET_PATH = "/var/run/MultiChannelAmpDaemon.sock"
STATUS_UPDATE_INTERVAL = 30  # Update status file every 30 seconds
DEBUG_MODE = False  # Will be set by command line argument

# Logging setup
logging.basicConfig(
    level=logging.INFO,  # Default level, will be changed to DEBUG if --debug is used
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/MultiChannelAmpDaemon.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('MultiChannelAmpDaemon')


class DeviceState(Enum):
    """Device power states"""
    OFF = 0
    ON = 1


@dataclass
class SoundcardConfig:
    """Configuration for a sound card"""
    id: int
    name: str
    gpioSuspend: int  # GPIO pin for SUSPEND signal
    gpioMute: int     # GPIO pin for MUTE signal
    gpioLed: int      # GPIO pin for status LED
    alsaCard: str     # ALSA card number
    usbDevice: str    # USB device path
    tempSensor: Optional[str]  # 1-wire temperature sensor ID (e.g., "28-0000...")
    players: Set[str]


def loadConfiguration(configPath):
    """
    Load configuration from YAML file

    Args:
        configPath: Path to YAML configuration file

    Returns:
        dict: Configuration dictionary
    """
    try:
        with open(configPath, 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Configuration loaded from: {configPath}")
        return config
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {configPath}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in configuration file: {e}")
        raise


class SoundcardController:
    """Controls a single sound card via GPIO"""

    def __init__(self, config: SoundcardConfig, daemon):
        self.config = config
        self.daemon = daemon  # Reference to parent daemon
        self.state = DeviceState.OFF
        self.activePlayers: Set[str] = set()
        self.lastActive = 0
        self.timer: threading.Timer = None
        self.lock = threading.Lock()
        self.setupGpio()

    def setupGpio(self):
        """Initializes GPIO pins for this sound card"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)

            # Setup SUSPEND pin (output)
            GPIO.setup(self.config.gpioSuspend, GPIO.OUT)
            GPIO.output(self.config.gpioSuspend, GPIO.HIGH)  # Start suspended

            # Setup MUTE pin (output)
            GPIO.setup(self.config.gpioMute, GPIO.OUT)
            GPIO.output(self.config.gpioMute, GPIO.HIGH)  # Start muted

            # Setup LED pin (output)
            GPIO.setup(self.config.gpioLed, GPIO.OUT)
            GPIO.output(self.config.gpioLed, GPIO.LOW)  # LED off

            logger.info(f"GPIO initialized for {self.config.name}: "
                       f"SUSPEND={self.config.gpioSuspend}, "
                       f"MUTE={self.config.gpioMute}, "
                       f"LED={self.config.gpioLed}")
        except Exception as e:
            logger.error(f"GPIO initialization failed for {self.config.name}: {e}")
            # Propagate error to daemon
            raise

    def activatePlayer(self, playerName: str):
        """Marks a player as active"""
        with self.lock:
            wasEmpty = len(self.activePlayers) == 0
            self.activePlayers.add(playerName)
            self.lastActive = time.time()

            # Cancel pending deactivation timer
            if self.timer:
                self.timer.cancel()
                self.timer = None

            # Activate sound card if needed
            if wasEmpty or self.state == DeviceState.OFF:
                self.activate()

    def deactivatePlayer(self, playerName: str):
        """Marks a player as inactive"""
        with self.lock:
            self.activePlayers.discard(playerName)

            # Schedule deactivation if no players are active
            if len(self.activePlayers) == 0:
                self.scheduleDeactivation()

    def activate(self):
        """Activates the sound card via GPIO sequence"""
        if self.state == DeviceState.ON:
            return

        logger.info(f"Activating sound card {self.config.name}")
        try:
            import RPi.GPIO as GPIO

            # Step 1: Set SUSPEND to 0 (active)
            GPIO.output(self.config.gpioSuspend, GPIO.LOW)
            logger.debug(f"{self.config.name}: SUSPEND set to LOW")

            # Wait for specified delay
            time.sleep(GPIO_DELAY)

            # Step 2: Set MUTE to 0 (unmuted)
            GPIO.output(self.config.gpioMute, GPIO.LOW)
            logger.debug(f"{self.config.name}: MUTE set to LOW")

            # Step 3: Turn on status LED
            GPIO.output(self.config.gpioLed, GPIO.HIGH)
            logger.debug(f"{self.config.name}: LED set to HIGH")

            self.state = DeviceState.ON
            logger.info(f"Sound card {self.config.name} activated")
        except Exception as e:
            logger.error(f"Exception activating {self.config.name}: {e}")

    def deactivate(self):
        """Deactivates the sound card via GPIO sequence with delay between mute and suspend"""
        with self.lock:
            # Double-check no players became active during timeout
            if len(self.activePlayers) > 0:
                logger.info(f"Deactivation of {self.config.name} cancelled - active players present")
                return

            if self.state == DeviceState.OFF:
                return

            logger.info(f"Deactivating sound card {self.config.name}")
            try:
                import RPi.GPIO as GPIO

                # Step 1: Set MUTE to 1 (muted)
                GPIO.output(self.config.gpioMute, GPIO.HIGH)
                logger.debug(f"{self.config.name}: MUTE set to HIGH")

                # Wait for mute-to-suspend delay (configurable)
                logger.debug(f"{self.config.name}: Waiting {SOUNDCARD_MUTE_DELAY}s before suspend")
                time.sleep(SOUNDCARD_MUTE_DELAY)

                # Check again if players became active during delay
                if len(self.activePlayers) > 0:
                    logger.info(f"Deactivation of {self.config.name} cancelled during mute delay")
                    # Unmute again
                    GPIO.output(self.config.gpioMute, GPIO.LOW)
                    return

                # Step 2: Set SUSPEND to 1 (suspended)
                GPIO.output(self.config.gpioSuspend, GPIO.HIGH)
                logger.debug(f"{self.config.name}: SUSPEND set to HIGH")

                # Wait for GPIO delay
                time.sleep(GPIO_DELAY)

                # Step 3: Turn off status LED
                GPIO.output(self.config.gpioLed, GPIO.LOW)
                logger.debug(f"{self.config.name}: LED set to LOW")

                self.state = DeviceState.OFF
                logger.info(f"Sound card {self.config.name} deactivated")

                # Check if power supply can be deactivated
                if self.daemon:
                    self.daemon.checkPowerSupplyDeactivation()

            except Exception as e:
                logger.error(f"Exception deactivating {self.config.name}: {e}")

    def scheduleDeactivation(self):
        """Schedules deactivation after timeout"""
        if self.timer:
            self.timer.cancel()

        logger.info(f"Scheduling deactivation of {self.config.name} in {SOUNDCARD_TIMEOUT}s")
        self.timer = threading.Timer(SOUNDCARD_TIMEOUT, self.deactivate)
        self.timer.daemon = True
        self.timer.start()

    def isActive(self) -> bool:
        """Checks if the sound card is active"""
        # Don't use lock here to avoid deadlock when called from daemon
        return self.state == DeviceState.ON


class PowerSupplyController:
    """Controls the main power supply via GPIO"""

    def __init__(self, gpioPin: int = GPIO_POWER_SUPPLY):
        self.gpioPin = gpioPin
        self.state = DeviceState.OFF
        self.timer: threading.Timer = None
        self.lock = threading.Lock()
        self.setupGpio()

    def setupGpio(self):
        """Initializes GPIO for power supply control"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpioPin, GPIO.OUT)
            GPIO.output(self.gpioPin, GPIO.HIGH)  # Start with power OFF (GPIO=1)
            logger.info(f"GPIO pin {self.gpioPin} initialized for power supply (HIGH=OFF, LOW=ON)")
        except Exception as e:
            logger.error(f"GPIO initialization failed: {e}")

    def activate(self):
        """Activates the power supply (GPIO=0)"""
        with self.lock:
            # Always cancel pending deactivation timer, even if already active
            if self.timer:
                logger.info("Cancelling pending power supply deactivation timer")
                self.timer.cancel()
                self.timer = None

            if self.state == DeviceState.ON:
                logger.debug("Power supply already active")
                return

            logger.info("Activating main power supply")
            try:
                import RPi.GPIO as GPIO
                GPIO.output(self.gpioPin, GPIO.LOW)  # LOW = ON
                self.state = DeviceState.ON
                logger.info("Main power supply activated (GPIO=LOW)")
            except Exception as e:
                logger.error(f"Error activating power supply: {e}")

    def scheduleDeactivation(self):
        """Schedules deactivation after timeout"""
        with self.lock:
            if self.timer:
                self.timer.cancel()

            logger.info(f"Scheduling power supply deactivation in {POWER_SUPPLY_TIMEOUT}s")
            self.timer = threading.Timer(POWER_SUPPLY_TIMEOUT, self.deactivate)
            self.timer.daemon = True
            self.timer.start()

    def deactivate(self):
        """Deactivates the power supply (GPIO=1)"""
        with self.lock:
            if self.state == DeviceState.OFF:
                return

            logger.info("Deactivating main power supply")
            try:
                import RPi.GPIO as GPIO
                GPIO.output(self.gpioPin, GPIO.HIGH)  # HIGH = OFF
                self.state = DeviceState.OFF
                logger.info("Main power supply deactivated (GPIO=HIGH)")
            except Exception as e:
                logger.error(f"Error deactivating power supply: {e}")

    def isActive(self) -> bool:
        """Checks if the power supply is active"""
        # Don't use lock here to avoid deadlock when called from daemon
        return self.state == DeviceState.ON


class AmpControlDaemon:
    """Main daemon for amplifier control"""

    def __init__(self, configPath=DEFAULT_CONFIG_PATH):
        self.configPath = configPath
        self.soundcards: Dict[int, SoundcardController] = {}
        self.playerToSoundcard: Dict[str, int] = {}

        # Load global config for GPIO pins
        config = loadConfiguration(configPath)
        globalConfig = config.get('global', {})

        gpioPower = globalConfig.get('gpio_power_supply', GPIO_POWER_SUPPLY)
        self.powerSupply = PowerSupplyController(gpioPin=gpioPower)

        self.running = False
        self.errorLedInitialized = False
        self.errorLedActive = False
        self.socketServer = None
        self.statusUpdateTimer = None
        self.setupErrorLed()
        self.setupSoundcards()

    def setupErrorLed(self):
        """Initializes error LED GPIO"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(GPIO_ERROR_LED, GPIO.OUT)
            GPIO.output(GPIO_ERROR_LED, GPIO.LOW)  # Start with error LED off
            self.errorLedInitialized = True
            self.errorLedActive = False
            logger.info(f"Error LED initialized on GPIO {GPIO_ERROR_LED}")
        except Exception as e:
            logger.error(f"Error LED initialization failed: {e}")

    def handleError(self, errorMsg: str, exception: Exception = None):
        """
        Handles critical errors by:
        1. Turning on error LED (GPIO 26)
        2. Turning off all sound cards
        3. Turning off power supply
        """
        if exception:
            logger.critical(f"Critical error: {errorMsg} - {exception}")
        else:
            logger.critical(f"Critical error: {errorMsg}")

        try:
            import RPi.GPIO as GPIO

            # Step 1: Turn on error LED FIRST
            if self.errorLedInitialized:
                try:
                    GPIO.output(GPIO_ERROR_LED, GPIO.HIGH)
                    self.errorLedActive = True
                    logger.info(f"Error LED activated on GPIO {GPIO_ERROR_LED}")
                except Exception as e:
                    logger.error(f"Failed to activate error LED: {e}")

            # Step 2: Turn off all sound cards
            logger.info("Emergency shutdown: Deactivating all sound cards")
            for soundcardId, soundcard in self.soundcards.items():
                try:
                    # Force immediate deactivation
                    if soundcard.state == DeviceState.ON:
                        GPIO.output(soundcard.config.gpioMute, GPIO.HIGH)
                        time.sleep(GPIO_DELAY)
                        GPIO.output(soundcard.config.gpioSuspend, GPIO.HIGH)
                        GPIO.output(soundcard.config.gpioLed, GPIO.LOW)
                        soundcard.state = DeviceState.OFF
                        logger.info(f"Emergency shutdown: {soundcard.config.name} deactivated")
                except Exception as e:
                    logger.error(f"Error during emergency shutdown of {soundcard.config.name}: {e}")

            # Step 3: Turn off power supply
            logger.info("Emergency shutdown: Deactivating power supply")
            try:
                if self.powerSupply.state == DeviceState.ON:
                    GPIO.output(self.powerSupply.gpioPin, GPIO.HIGH)  # HIGH = OFF
                    self.powerSupply.state = DeviceState.OFF
                    logger.info("Emergency shutdown: Power supply deactivated")
            except Exception as e:
                logger.error(f"Error during power supply shutdown: {e}")

        except Exception as e:
            logger.critical(f"Exception during error handling: {e}")

    def setupSoundcards(self):
        """Initializes sound card configuration from config file"""

        # Load configuration
        config = loadConfiguration(self.configPath)

        # Update global timeouts if not in debug mode
        global SOUNDCARD_TIMEOUT, POWER_SUPPLY_TIMEOUT, GPIO_DELAY, SOUNDCARD_MUTE_DELAY
        if not DEBUG_MODE:
            globalConfig = config.get('global', {})
            SOUNDCARD_TIMEOUT = globalConfig.get('soundcard_timeout', SOUNDCARD_TIMEOUT)
            POWER_SUPPLY_TIMEOUT = globalConfig.get('power_supply_timeout', POWER_SUPPLY_TIMEOUT)
            GPIO_DELAY = globalConfig.get('gpio_delay', GPIO_DELAY)
            SOUNDCARD_MUTE_DELAY = globalConfig.get('soundcard_mute_delay', SOUNDCARD_MUTE_DELAY)

            logger.info(f"Timeouts from config: Soundcard={SOUNDCARD_TIMEOUT}s, PowerSupply={POWER_SUPPLY_TIMEOUT}s, MuteDelay={SOUNDCARD_MUTE_DELAY}s")

        # Parse soundcard configurations
        soundcardsConfig = config.get('soundcards', [])
        if not soundcardsConfig:
            raise ValueError("No soundcards defined in configuration file")

        try:
            for scConfig in soundcardsConfig:
                # Extract GPIO configuration
                gpio = scConfig.get('gpio', {})

                # Build player set
                players = set()
                for player in scConfig.get('players', []):
                    players.add(player['name'])

                # Create SoundcardConfig
                soundcardConfig = SoundcardConfig(
                    id=scConfig['id'],
                    name=scConfig['name'],
                    gpioSuspend=gpio['suspend'],
                    gpioMute=gpio['mute'],
                    gpioLed=gpio['led'],
                    alsaCard=scConfig['alsa_card'],
                    usbDevice=scConfig['usb_device'],
                    tempSensor=scConfig.get('temp_sensor'),  # Optional 1-wire sensor
                    players=players
                )

                # Create controller
                self.soundcards[soundcardConfig.id] = SoundcardController(soundcardConfig, self)

                # Map players to soundcard
                for playerName in players:
                    self.playerToSoundcard[playerName] = soundcardConfig.id

                logger.info(f"Configured {soundcardConfig.name}: {len(players)} players, "
                           f"GPIO(S={gpio['suspend']}, M={gpio['mute']}, L={gpio['led']})")

            logger.info(f"Initialized with {len(self.soundcards)} sound cards, {len(self.playerToSoundcard)} total players")

        except Exception as e:
            self.handleError("Failed to initialize sound cards from configuration", e)
            raise

    def handlePlayerEvent(self, playerName: str, state: int):
        """
        Processes Squeezelite events
        playerName: Name of the player
        state: 1 = play, 0 = stop
        """
        try:
            if playerName not in self.playerToSoundcard:
                logger.warning(f"Unknown player: {playerName}")
                return

            soundcardId = self.playerToSoundcard[playerName]
            soundcard = self.soundcards[soundcardId]

            if state == 1:
                logger.info(f"Player {playerName} starting playback")
                # Always call activate to cancel any pending deactivation timer
                self.powerSupply.activate()

                # Activate sound card
                soundcard.activatePlayer(playerName)
            else:
                logger.info(f"Player {playerName} stopping playback")
                soundcard.deactivatePlayer(playerName)

                # Check if power supply can be deactivated
                self.checkPowerSupplyDeactivation()
        except Exception as e:
            self.handleError(f"Error handling player event for {playerName}", e)

    def checkPowerSupplyDeactivation(self):
        """Checks if power supply can be deactivated"""
        logger.info("Checking if power supply can be deactivated")

        anyActive = any(sc.isActive() for sc in self.soundcards.values())

        logger.info(f"Any soundcard active: {anyActive}, Power supply active: {self.powerSupply.isActive()}")

        if not anyActive and self.powerSupply.isActive():
            logger.info("All soundcards inactive - scheduling power supply deactivation")
            self.powerSupply.scheduleDeactivation()
        else:
            logger.info("Power supply deactivation not needed")

    def readTemperature(self, sensorId: str) -> Optional[float]:
        """
        Read temperature from 1-wire sensor

        Args:
            sensorId: 1-wire sensor ID (e.g., "28-00000abcdef0")

        Returns:
            Temperature in Celsius or None if error
        """
        if not sensorId:
            return None

        sensorPath = f"/sys/bus/w1/devices/{sensorId}/w1_slave"

        try:
            with open(sensorPath, 'r') as f:
                lines = f.readlines()

            # Check if reading is valid (CRC OK)
            if len(lines) < 2 or 'YES' not in lines[0]:
                logger.warning(f"Temperature sensor {sensorId}: CRC check failed")
                return None

            # Extract temperature value
            # Format: "... t=23625" means 23.625°C
            tempPos = lines[1].find('t=')
            if tempPos != -1:
                tempStr = lines[1][tempPos + 2:].strip()
                tempC = float(tempStr) / 1000.0
                return tempC
            else:
                logger.warning(f"Temperature sensor {sensorId}: Could not parse temperature")
                return None

        except FileNotFoundError:
            logger.warning(f"Temperature sensor {sensorId} not found at {sensorPath}")
            return None
        except Exception as e:
            logger.error(f"Error reading temperature sensor {sensorId}: {e}")
            return None

    def getStatus(self) -> Dict:
        """Get current system status"""
        status = {
            'timestamp': time.time(),
            'power_supply': {
                'state': 'on' if self.powerSupply.isActive() else 'off',
                'active': self.powerSupply.isActive()
            },
            'error_led': {
                'state': 'on' if self.errorLedActive else 'off',
                'active': self.errorLedActive
            },
            'soundcards': {}
        }

        for scId, sc in self.soundcards.items():
            # Determine state based on GPIO and active players
            if len(sc.activePlayers) > 0:
                state = 'on'
            elif sc.isActive():
                state = 'muted'  # Active but no players
            else:
                state = 'suspended'

            # Read temperature if sensor configured
            temperature = None
            if sc.config.tempSensor:
                temperature = round(self.readTemperature(sc.config.tempSensor),1)

            status['soundcards'][scId] = {
                'id': scId,
                'name': sc.config.name,
                'state': state,
                'active': sc.isActive(),
                'active_players': list(sc.activePlayers),
                'player_count': len(sc.activePlayers),
                'temperature': temperature,
                'temp_sensor': sc.config.tempSensor
            }

        return status

    def writeStatusFile(self):
        """Write current status to JSON file"""
        try:
            import json
            status = self.getStatus()

            # Write atomically (write to temp file, then rename)
            tempFile = STATUS_JSON_FILE + '.tmp'
            with open(tempFile, 'w') as f:
                json.dump(status, f, indent=2)

            # Atomic rename
            os.rename(tempFile, STATUS_JSON_FILE)

            logger.debug(f"Status file updated: {STATUS_JSON_FILE}")

        except Exception as e:
            logger.error(f"Failed to write status file: {e}")

    def scheduleStatusUpdate(self):
        """Schedule periodic status file updates"""
        if not self.running:
            return

        self.writeStatusFile()

        # Schedule next update
        self.statusUpdateTimer = threading.Timer(STATUS_UPDATE_INTERVAL, self.scheduleStatusUpdate)
        self.statusUpdateTimer.daemon = True
        self.statusUpdateTimer.start()

    def startSocketServer(self):
        """Starts Unix socket server for receiving events"""
        # Remove old socket file if exists
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            if os.path.exists(SOCKET_PATH):
                raise

        # Create socket
        self.socketServer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socketServer.bind(SOCKET_PATH)
        self.socketServer.listen(5)

        # Set permissions so squeezelite can connect
        os.chmod(SOCKET_PATH, 0o666)

        logger.info(f"Socket server listening on {SOCKET_PATH}")

        # Accept connections in separate thread
        socketThread = threading.Thread(target=self.acceptConnections, daemon=True)
        socketThread.start()

    def acceptConnections(self):
        """Accepts incoming socket connections"""
        while self.running:
            try:
                conn, addr = self.socketServer.accept()
                # Handle connection in separate thread
                clientThread = threading.Thread(
                    target=self.handleConnection,
                    args=(conn,),
                    daemon=True
                )
                clientThread.start()
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")

    def handleConnection(self, conn):
        """Handles a single client connection"""
        try:
            data = conn.recv(1024).decode('utf-8').strip()

            if not data:
                return

            # Expected format: "playername:state"
            parts = data.split(':')
            if len(parts) != 2:
                logger.warning(f"Invalid message format: {data}")
                return

            playerName = parts[0]
            state = int(parts[1])

            # Process event
            self.handlePlayerEvent(playerName, state)

            # Send acknowledgment
            conn.send(b"OK\n")

        except Exception as e:
            logger.error(f"Error handling connection: {e}")
        finally:
            conn.close()

    def start(self):
        """Starts the daemon"""
        self.running = True
        logger.info("="*80)
        logger.info("=" + " "*78 + "=")
        if DEBUG_MODE:
            logger.info("=  MULTI-CHANNEL AMP DAEMON STARTING (DEBUG MODE)" + " "*29 + "=")
            logger.info(f"=  Version: {VERSION}" + " "*(80-14-len(VERSION)) + "=")
            logger.info(f"=  Soundcard timeout: {SOUNDCARD_TIMEOUT}s, Power supply timeout: {POWER_SUPPLY_TIMEOUT}s" + " "*(80-73-len(str(SOUNDCARD_TIMEOUT))-len(str(POWER_SUPPLY_TIMEOUT))) + "=")
        else:
            logger.info("=  MULTI-CHANNEL AMP DAEMON STARTING" + " "*42 + "=")
            logger.info(f"=  Version: {VERSION}" + " "*(80-14-len(VERSION)) + "=")
        logger.info("=" + " "*78 + "=")
        logger.info("="*80)

        # Signal handlers for clean shutdown
        signal.signal(signal.SIGTERM, self.signalHandler)
        signal.signal(signal.SIGINT, self.signalHandler)

        # Create status file
        Path(STATUS_FILE).write_text("running")

        # Start socket server
        try:
            self.startSocketServer()
        except Exception as e:
            logger.error(f"Failed to start socket server: {e}")
            self.handleError("Socket server startup failed", e)
            sys.exit(1)

        # Start status file updates
        self.scheduleStatusUpdate()

        # Main loop
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def signalHandler(self, signum, frame):
        """Handler for shutdown signals"""
        logger.info(f"Signal {signum} received, shutting down...")
        self.stop()

    def stop(self):
        """Stops the daemon"""
        self.running = False
        logger.info("Multi-Channel Amp Daemon shutting down")

        # Stop status updates
        if self.statusUpdateTimer:
            self.statusUpdateTimer.cancel()

        # Turn on error LED during shutdown
        if self.errorLedInitialized:
            try:
                import RPi.GPIO as GPIO
                GPIO.output(GPIO_ERROR_LED, GPIO.HIGH)
                self.errorLedActive = True
                logger.info("Error LED activated during shutdown")
            except Exception as e:
                logger.error(f"Failed to activate error LED during shutdown: {e}")

        # Write final status
        self.writeStatusFile()

        # Close socket server
        if self.socketServer:
            try:
                self.socketServer.close()
                os.unlink(SOCKET_PATH)
            except:
                pass

        # Cleanup status file
        try:
            Path(STATUS_FILE).unlink()
        except:
            pass

        # Cleanup PID file
        try:
            Path(PID_FILE).unlink()
        except:
            pass

        # Cleanup JSON status file
        try:
            Path(STATUS_JSON_FILE).unlink()
        except:
            pass

        sys.exit(0)


def checkAlreadyRunning():
    """
    Checks if daemon is already running by checking PID file
    Returns True if already running, False otherwise
    """
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        # Check if process with this PID exists
        try:
            os.kill(pid, 0)  # Doesn't actually kill, just checks if process exists
            logger.error(f"Daemon already running with PID {pid}")
            return True
        except OSError:
            # Process doesn't exist, remove stale PID file
            logger.warning(f"Removing stale PID file (PID {pid} not running)")
            os.unlink(PID_FILE)
            return False

    except (ValueError, IOError) as e:
        logger.warning(f"Error reading PID file: {e}")
        try:
            os.unlink(PID_FILE)
        except:
            pass
        return False


def writePidFile():
    """Writes current process ID to PID file"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID file created: {PID_FILE} (PID: {os.getpid()})")
    except Exception as e:
        logger.error(f"Failed to write PID file: {e}")
        raise


def main():
    """Main entry point"""
    global SOUNDCARD_TIMEOUT, POWER_SUPPLY_TIMEOUT, DEBUG_MODE

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Multi-Channel Amplifier Control Daemon',
        epilog=f'Version {VERSION}'
    )
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode (verbose logging, shorter timeouts)')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    parser.add_argument('--config', '-c',
                       default=DEFAULT_CONFIG_PATH,
                       help=f'Path to configuration file (default: {DEFAULT_CONFIG_PATH})')
    args = parser.parse_args()

    # Configure debug mode
    if args.debug:
        DEBUG_MODE = True
        logger.setLevel(logging.DEBUG)
        SOUNDCARD_TIMEOUT = 1 * 60  # 1 minute in debug mode
        POWER_SUPPLY_TIMEOUT = 2 * 60  # 2 minutes in debug mode
        logger.debug("Debug mode enabled")
        logger.debug(f"Soundcard timeout: {SOUNDCARD_TIMEOUT}s")
        logger.debug(f"Power supply timeout: {POWER_SUPPLY_TIMEOUT}s")

    # Check if already running
    if checkAlreadyRunning():
        print("ERROR: Daemon is already running!", file=sys.stderr)
        print(f"Check PID file: {PID_FILE}", file=sys.stderr)
        sys.exit(1)

    # Write PID file
    try:
        writePidFile()
    except Exception as e:
        print(f"ERROR: Failed to create PID file: {e}", file=sys.stderr)
        sys.exit(1)

    # Start daemon with config file
    try:
        daemon = AmpControlDaemon(configPath=args.config)
        daemon.start()
    except Exception as e:
        print(f"ERROR: Failed to start daemon: {e}", file=sys.stderr)
        logger.critical(f"Fatal error during startup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
