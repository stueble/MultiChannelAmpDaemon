#!/usr/bin/env python3
"""
Squeezelite Launcher
Starts all Squeezelite instances based on MultiChannelAmpDaemon configuration

Version: 1.0.0
"""

import yaml
import sys
import logging
import os
import subprocess
import signal
import time
from pathlib import Path

DEFAULT_CONFIG_PATH = "/etc/MultiChannelAmpDaemon.yaml"
PID_DIR = "/var/run/squeezelite"

# Logging setup
logging.basicConfig(
    level=logging.INFO,  # Default level, will be changed to DEBUG if --debug is used
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/squeezelite-launcher.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('squeezelite-launcher')

class SqueezeliteLauncher:
    """Manages multiple Squeezelite instances"""

    def __init__(self, configPath):
        self.configPath = configPath
        self.config = None
        self.processes = {}  # player_name -> subprocess.Popen
        self.running = False

    def loadConfig(self):
        """Load configuration from YAML file"""
        try:
            with open(self.configPath, 'r') as f:
                self.config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from: {self.configPath}")
        except FileNotFoundError:
            logger.error(f"ERROR: Configuration file not found: {self.configPath}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"ERROR: Invalid YAML in configuration file: {e}")
            sys.exit(1)

    def buildSqueezeliteCommand(self, player, soundcard):
        """Build squeezelite command line arguments"""
        sqConfig = self.config.get('squeezelite', {})
        binary = sqConfig.get('binary', '/usr/bin/squeezelite')
        callback = sqConfig.get('callback_script', '/usr/local/bin/MultiChannelAmpCallback.py')
        commonOpts = sqConfig.get('common_options', [])
        lmsServer = sqConfig.get('lms_server')

        cmd = [binary]

        # Player name
        cmd.extend(['-n', f'"{player['description']}"'])

        # Output device
        cmd.extend(['-o', player['alsa_device']])

        # Callback script
        cmd.extend(['-S', f"'{callback} {player['name']}'"])

        # MAC address (if specified)
        if 'mac_address' in player:
            cmd.extend(['-m', player['mac_address']])

        # LMS server (if specified)
        if lmsServer:
            cmd.extend(['-s', lmsServer])

        # Common options (parse string options)
        for opt in commonOpts:
            cmd.extend(opt.split())

        return cmd

    def startPlayer(self, player, soundcard):
        """Start a single Squeezelite instance"""
        playerName = player['name']
        cmd = self.buildSqueezeliteCommand(player, soundcard)

        try:
            # Create PID directory if needed
            os.makedirs(PID_DIR, exist_ok=True)

            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True  # Detach from parent
            )

            self.processes[playerName] = process

            # Write PID file
            pidFile = Path(PID_DIR) / f"{playerName}.pid"
            pidFile.write_text(str(process.pid))

            logger.info(f"✓ Started {playerName} (PID: {process.pid})")
            logger.info(f"  Command: {' '.join(cmd)}")

            return True

        except Exception as e:
            logger.error(f"✗ Failed to start {playerName}: {e}")
            return False

    def startAllPlayers(self):
        """Start all Squeezelite instances from configuration"""
        logger.info("Starting all Squeezelite instances...")
        logger.info("="*80)

        soundcards = self.config.get('soundcards', [])
        if not soundcards:
            logger.error("ERROR: No soundcards defined in configuration")
            return False

        successCount = 0
        totalCount = 0

        for soundcard in soundcards:
            players = soundcard.get('players', [])
            logger.info(f"\nSoundcard: {soundcard['name']} ({len(players)} players)")

            for player in players:
                totalCount += 1
                if self.startPlayer(player, soundcard):
                    successCount += 1

        logger.info("\n" + "="*80)
        logger.info(f"Started {successCount}/{totalCount} Squeezelite instances")
        logger.info("="*80)

        return successCount == totalCount

    def stopPlayer(self, playerName):
        """Stop a single Squeezelite instance"""
        if playerName not in self.processes:
            return

        process = self.processes[playerName]

        try:
            # Try graceful shutdown first
            process.terminate()

            # Wait up to 5 seconds
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if still running
                process.kill()
                process.wait()

            logger.info(f"✓ Stopped {playerName}")

            # Remove PID file
            pidFile = Path(PID_DIR) / f"{playerName}.pid"
            try:
                pidFile.unlink()
            except:
                pass

            del self.processes[playerName]

        except Exception as e:
            logger.error(f"✗ Error stopping {playerName}: {e}")

    def stopAllPlayers(self):
        """Stop all running Squeezelite instances"""
        logger.info("\nStopping all Squeezelite instances...")

        playerNames = list(self.processes.keys())
        for playerName in playerNames:
            self.stopPlayer(playerName)

        logger.info("All Squeezelite instances stopped")

    def monitorProcesses(self):
        """Monitor processes and restart if they crash"""
        while self.running:
            time.sleep(5)  # Check every 5 seconds

            # Check each process
            for playerName, process in list(self.processes.items()):
                returncode = process.poll()

                # Process has terminated
                if returncode is not None:
                    logger.error(f"⚠ Player {playerName} terminated (code: {returncode})", file=sys.stderr)

                    # Find player config and restart
                    for soundcard in self.config.get('soundcards', []):
                        for player in soundcard.get('players', []):
                            if player['name'] == playerName:
                                logger.info(f"↻ Restarting {playerName}...")
                                del self.processes[playerName]
                                self.startPlayer(player, soundcard)
                                break

    def signalHandler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"\nReceived signal {signum}, shutting down...")
        self.running = False
        self.stopAllPlayers()
        sys.exit(0)

    def run(self):
        """Main run loop"""
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.signalHandler)
        signal.signal(signal.SIGINT, self.signalHandler)

        # Load configuration
        self.loadConfig()

        # Start all players
        if not self.startAllPlayers():
            logger.error("ERROR: Failed to start all players")
            sys.exit(1)

        # Monitor processes
        self.running = True
        logger.info("\nMonitoring Squeezelite instances... (Ctrl+C to stop)")

        try:
            self.monitorProcesses()
        except KeyboardInterrupt:
            pass
        finally:
            self.stopAllPlayers()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Squeezelite Launcher - Start all instances from config',
        epilog='Version 1.0.0'
    )
    parser.add_argument(
        '--config', '-c',
        default=DEFAULT_CONFIG_PATH,
        help=f'Path to configuration file (default: {DEFAULT_CONFIG_PATH})'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )

    args = parser.parse_args()

    launcher = SqueezeliteLauncher(args.config)
    launcher.run()


if __name__ == "__main__":
    main()
