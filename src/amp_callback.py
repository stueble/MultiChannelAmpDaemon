#!/usr/bin/env python3
"""
Callback script for Squeezelite
Sends player events to the amp control daemon via Unix socket

Usage from Squeezelite:
  squeezelite -n wohnzimmer -S "/usr/local/bin/amp_callback.py wohnzimmer"
"""

import socket
import sys
import os

SOCKET_PATH = "/var/run/amp_control.sock"
TIMEOUT = 5  # seconds


def sendEvent(playerName: str, state: int) -> bool:
    """
    Sends a player event to the daemon

    Args:
        playerName: Name of the player
        state: 1 for play, 0 for stop

    Returns:
        True if successful, False otherwise
    """
    try:
        # Create socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)

        # Connect to daemon
        sock.connect(SOCKET_PATH)

        # Send message in format "playername:state"
        message = f"{playerName}:{state}\n"
        sock.send(message.encode('utf-8'))

        # Wait for acknowledgment
        response = sock.recv(1024).decode('utf-8').strip()

        sock.close()

        if response == "OK":
            return True
        else:
            print(f"Unexpected response: {response}", file=sys.stderr)
            return False

    except socket.timeout:
        print(f"Timeout connecting to daemon at {SOCKET_PATH}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"Daemon socket not found at {SOCKET_PATH}", file=sys.stderr)
        print("Is the amp_control daemon running?", file=sys.stderr)
        return False
    except ConnectionRefusedError:
        print(f"Connection refused to {SOCKET_PATH}", file=sys.stderr)
        print("Is the amp_control daemon running?", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error sending event: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point"""
    # Check arguments
    if len(sys.argv) != 3:
        print("Usage: amp_callback.py <player_name> <state>", file=sys.stderr)
        print("  player_name: Name of the Squeezelite player", file=sys.stderr)
        print("  state: 1 for play, 0 for stop", file=sys.stderr)
        sys.exit(1)

    playerName = sys.argv[1]

    # Validate state
    try:
        state = int(sys.argv[2])
        if state not in [0, 1]:
            raise ValueError("State must be 0 or 1")
    except ValueError as e:
        print(f"Invalid state argument: {sys.argv[2]} - {e}", file=sys.stderr)
        sys.exit(1)

    # Send event to daemon
    success = sendEvent(playerName, state)

    if not success:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
