# MultiChannelAmpCallback.py - Technical Specification

## Version: 1.0.0

## Overview
A lightweight Python callback script that acts as a bridge between Squeezelite audio players and the MultiChannelAmpDaemon. When Squeezelite starts or stops playback, it calls this script which forwards the event to the daemon via Unix socket.

## Purpose
- Translate Squeezelite playback events into daemon notifications
- Provide reliable communication between Squeezelite and the daemon
- Enable automatic power management based on audio playback activity
- Support multiple Squeezelite instances running simultaneously

## How Squeezelite Callbacks Work

### Squeezelite -S Parameter
Squeezelite supports a `-S` parameter that specifies a script to execute on playback state changes:

```bash
squeezelite -S "<script_path> <additional_args>"
```

**Important:** Squeezelite only passes ONE argument to the script: the state value.

### State Values
Squeezelite passes these state values:
- `0` = Stop (playback stopped)
- `1` = Play (playback started/resumed)
- `2` = Pause (playback paused)

### Invocation Pattern
When configured as:
```bash
squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer"
```

Squeezelite will execute:
```bash
/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer 1  # On play
/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer 0  # On stop
/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer 2  # On pause
```

**Note:** The player name ("wohnzimmer") must be included in the -S command because Squeezelite does NOT provide it automatically.

## File Specification

### Location
`/usr/local/bin/MultiChannelAmpCallback.py`

### Permissions
- Executable: `chmod +x`
- Owner: root or squeezelite user
- Readable by all (for debugging)

### Dependencies
- Python 3.7+
- Standard library only: socket, sys, os, logging
- No external packages required

## Functional Requirements

### Command-Line Interface

**Usage:**
```bash
MultiChannelAmpCallback.py <player_name> <state>
```

**Arguments:**
1. `player_name` (required): Name of the Squeezelite player
   - Must match a player defined in daemon configuration
   - Examples: "wohnzimmer", "schlafzimmer", "kian"
   
2. `state` (required): Playback state as integer
   - `0` = Stop
   - `1` = Play
   - `2` = Pause (treated same as play by daemon)
   - Must be exactly 0, 1, or 2

**Exit Codes:**
- `0` = Success (event sent to daemon)
- `1` = Error (invalid arguments, connection failed, timeout)

### Communication Protocol

**Socket Connection:**
- Socket path: `/var/run/MultiChannelAmpDaemon.sock`
- Type: Unix domain socket (AF_UNIX, SOCK_STREAM)
- Timeout: 5 seconds
- Connection method: Connect, send, wait for ACK, close

**Message Format:**
```
playername:state\n
```

Examples:
```
wohnzimmer:1\n
schlafzimmer:0\n
kian:2\n
```

**Response Format:**
```
OK\n
```

The callback waits for this acknowledgment before considering the operation successful.

### Error Handling

**Connection Errors:**
1. **Socket not found** (FileNotFoundError)
   - Error message: "Daemon socket not found at /var/run/MultiChannelAmpDaemon.sock"
   - Hint: "Is the MultiChannelAmpDaemon running?"
   - Exit code: 1

2. **Connection refused** (ConnectionRefusedError)
   - Error message: "Connection refused to /var/run/MultiChannelAmpDaemon.sock"
   - Hint: "Is the MultiChannelAmpDaemon running?"
   - Exit code: 1

3. **Timeout** (socket.timeout)
   - Error message: "Timeout connecting to daemon at /var/run/MultiChannelAmpDaemon.sock"
   - Exit code: 1

**Argument Errors:**
1. **Wrong number of arguments**
   - Print usage information
   - Exit code: 1

2. **Invalid state value**
   - Error message: "Invalid state argument: {value} - State must be 0 or 1"
   - Exit code: 1

**All errors written to stderr for Squeezelite logging**

### Logging

**Log File:** `/var/log/MultiChannelAmpCallback.log`

**Log Level:** DEBUG (all invocations logged)

**Log Format:** 
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

**Logged Events:**
1. Every invocation with arguments
2. Socket connection attempts
3. Messages sent to daemon
4. Responses received
5. All errors with full details

**Example Log Entries:**
```
2026-02-03 14:23:45 - callback - INFO - Callback invoked with args: ['MultiChannelAmpCallback.py', 'wohnzimmer', '1']
2026-02-03 14:23:45 - callback - INFO - Sending event: player=wohnzimmer, state=1
2026-02-03 14:23:45 - callback - DEBUG - Connecting to /var/run/MultiChannelAmpDaemon.sock
2026-02-03 14:23:45 - callback - DEBUG - Sending message: wohnzimmer:1
2026-02-03 14:23:45 - callback - DEBUG - Received response: OK
2026-02-03 14:23:45 - callback - INFO - Event sent successfully
```

## Code Structure

### Main Components

**1. Constants:**
```python
SOCKET_PATH = "/var/run/MultiChannelAmpDaemon.sock"
TIMEOUT = 5  # seconds
```

**2. Function: sendEvent(playerName: str, state: int) -> bool**

Purpose: Send event to daemon via Unix socket

Parameters:
- playerName: Name of the player
- state: 0, 1, or 2

Returns:
- True if successful
- False on any error

Logic:
1. Create Unix socket
2. Set timeout to 5 seconds
3. Connect to daemon socket
4. Send message in format "playername:state\n"
5. Wait for "OK\n" response
6. Close socket
7. Return success/failure

**3. Function: main()**

Purpose: Entry point, validates arguments and calls sendEvent

Logic:
1. Check argument count (must be exactly 3 including script name)
2. Extract player_name from sys.argv[1]
3. Validate and parse state from sys.argv[2]
4. Call sendEvent()
5. Exit with appropriate code

### Error Handling Details

**Try-Catch Structure:**
```python
try:
    # Socket operations
except socket.timeout:
    # Log timeout
    # Print error to stderr
    return False
except FileNotFoundError:
    # Log socket not found
    # Print error and hint to stderr
    return False
except ConnectionRefusedError:
    # Log connection refused
    # Print error and hint to stderr
    return False
except Exception as e:
    # Log unexpected error
    # Print generic error to stderr
    return False
```

## Integration with Squeezelite

### Basic Usage

**Single Instance:**
```bash
squeezelite -n wohnzimmer \
  -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer" \
  -o hw:4,0
```

**With Additional Options:**
```bash
squeezelite -n wohnzimmer \
  -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer" \
  -o hw:4,0 \
  -a 80:4:: \
  -b 500:2000 \
  -C 5 \
  -s 192.168.1.100 \
  -m aa:bb:cc:dd:ee:01
```

### Multiple Instances

**Example: All three soundcards with multiple players**

```bash
# KAB9_1 players (hw:4,x)
squeezelite -n wohnzimmer   -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer"   -o hw:4,0 -s 192.168.1.100 &
squeezelite -n tvzimmer     -S "/usr/local/bin/MultiChannelAmpCallback.py tvzimmer"     -o hw:4,1 -s 192.168.1.100 &
squeezelite -n kueche       -S "/usr/local/bin/MultiChannelAmpCallback.py kueche"       -o hw:4,2 -s 192.168.1.100 &
squeezelite -n gaestezimmer -S "/usr/local/bin/MultiChannelAmpCallback.py gaestezimmer" -o hw:4,3 -s 192.168.1.100 &

# KAB9_2 players (hw:3,x)
squeezelite -n schlafzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py schlafzimmer" -o hw:3,0 -s 192.168.1.100 &
squeezelite -n terrasse     -S "/usr/local/bin/MultiChannelAmpCallback.py terrasse"     -o hw:3,1 -s 192.168.1.100 &
squeezelite -n gwc          -S "/usr/local/bin/MultiChannelAmpCallback.py gwc"          -o hw:3,2 -s 192.168.1.100 &
squeezelite -n elternbad    -S "/usr/local/bin/MultiChannelAmpCallback.py elternbad"    -o hw:3,3 -s 192.168.1.100 &
squeezelite -n balkon       -S "/usr/local/bin/MultiChannelAmpCallback.py balkon"       -o hw:3,4 -s 192.168.1.100 &
squeezelite -n sauna        -S "/usr/local/bin/MultiChannelAmpCallback.py sauna"        -o hw:3,5 -s 192.168.1.100 &

# KAB9_3 players (hw:0,x)
squeezelite -n kian         -S "/usr/local/bin/MultiChannelAmpCallback.py kian"         -o hw:0,0 -s 192.168.1.100 &
squeezelite -n sarina       -S "/usr/local/bin/MultiChannelAmpCallback.py sarina"       -o hw:0,1 -s 192.168.1.100 &
squeezelite -n hobbyraum    -S "/usr/local/bin/MultiChannelAmpCallback.py hobbyraum"    -o hw:0,2 -s 192.168.1.100 &
```

### Systemd Integration

See `squeezelite-launcher.py` specification for automated multi-instance management via systemd.

## Testing and Debugging

### Manual Testing

**1. Test callback directly:**
```bash
# Simulate play event
/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer 1

# Simulate stop event
/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer 0

# Expected output: None (success) or error message (failure)
# Check exit code:
echo $?  # Should be 0 on success
```

**2. Test with netcat:**
```bash
# Send event directly to daemon socket
echo "wohnzimmer:1" | nc -U /var/run/MultiChannelAmpDaemon.sock
# Should respond with: OK
```

**3. Monitor callback log:**
```bash
tail -f /var/log/MultiChannelAmpCallback.log
```

**4. Monitor daemon log:**
```bash
tail -f /var/log/MultiChannelAmpDaemon.log | grep -E "(wohnzimmer|Player)"
```

**5. Test with Squeezelite:**
```bash
# Start single instance with debug
squeezelite -n test_player \
  -S "/usr/local/bin/MultiChannelAmpCallback.py test_player" \
  -o hw:4,0 \
  -d all=debug

# Play something from LMS
# Watch both log files for activity
```

### Debug Checklist

**Problem: Callback not being called**
1. Check Squeezelite command line includes -S parameter
2. Verify callback script path is correct
3. Verify callback script is executable
4. Check Squeezelite logs for callback execution
5. Verify player name matches daemon configuration

**Problem: Connection fails**
1. Check if daemon is running: `ps aux | grep MultiChannelAmpDaemon`
2. Check if socket exists: `ls -l /var/run/MultiChannelAmpDaemon.sock`
3. Check socket permissions: Should be writable
4. Check daemon logs for socket creation
5. Try manual socket connection with netcat

**Problem: Events not processed**
1. Check daemon logs for received events
2. Verify player name is in daemon configuration
3. Check daemon status file for player activity
4. Verify soundcard is being activated (check GPIO states)

### Test Script

Create `/usr/local/bin/test-callback.sh`:

```bash
#!/bin/bash
echo "Testing MultiChannelAmpCallback..."

# Check if callback exists
if [ ! -f /usr/local/bin/MultiChannelAmpCallback.py ]; then
    echo "ERROR: Callback not found"
    exit 1
fi

# Check if executable
if [ ! -x /usr/local/bin/MultiChannelAmpCallback.py ]; then
    echo "ERROR: Callback not executable"
    exit 1
fi

# Check if daemon socket exists
if [ ! -S /var/run/MultiChannelAmpDaemon.sock ]; then
    echo "ERROR: Daemon socket not found. Is daemon running?"
    exit 1
fi

# Test play event
echo -n "Testing play event... "
/usr/local/bin/MultiChannelAmpCallback.py test_player 1
if [ $? -eq 0 ]; then
    echo "OK"
else
    echo "FAILED"
    exit 1
fi

sleep 2

# Test stop event
echo -n "Testing stop event... "
/usr/local/bin/MultiChannelAmpCallback.py test_player 0
if [ $? -eq 0 ]; then
    echo "OK"
else
    echo "FAILED"
    exit 1
fi

echo ""
echo "All tests passed!"
echo "Check logs:"
echo "  tail -f /var/log/MultiChannelAmpCallback.log"
echo "  tail -f /var/log/MultiChannelAmpDaemon.log"
```

## Event Flow Diagram

```
[Squeezelite] --starts playback-->
    |
    v
[Calls callback script with args: playername 1]
    |
    v
[MultiChannelAmpCallback.py]
    |
    +-- Validates arguments
    +-- Opens Unix socket
    +-- Sends "playername:1\n"
    +-- Waits for "OK\n"
    +-- Logs event
    +-- Exits with code 0
    |
    v
[MultiChannelAmpDaemon]
    |
    +-- Receives event on socket
    +-- Parses "playername:1"
    +-- Finds soundcard for player
    +-- Activates power supply if needed
    +-- Activates soundcard
    +-- Sends "OK\n" response
    +-- Updates status file
    |
    v
[GPIO pins change]
    |
    +-- Power supply: LOW (ON)
    +-- Soundcard SUSPEND: LOW
    +-- Soundcard MUTE: LOW
    +-- Soundcard LED: HIGH
```

## Performance Considerations

### Speed
- Socket connection: < 10ms typically
- Total callback execution: < 50ms
- Non-blocking for Squeezelite
- Squeezelite continues playback immediately

### Resource Usage
- Memory: < 5MB per execution
- CPU: Negligible (< 1% for < 100ms)
- Disk I/O: One log write per invocation

### Concurrency
- Multiple callbacks can run simultaneously
- Daemon handles concurrent socket connections
- No race conditions (daemon uses proper locking)

## Security Considerations

### File Permissions
- Script: 755 (rwxr-xr-x) - executable by all
- Log file: 644 (rw-r--r--) - readable by all
- Socket: 666 (rw-rw-rw-) - writable by all

### Trust Model
- Assumes local system is trusted
- No authentication on socket
- Daemon validates player names
- Invalid players logged but ignored

### Attack Vectors
- Socket flooding: Daemon rate-limits acceptable
- Invalid data: Daemon validates format
- Path traversal: Not applicable (fixed socket path)

## Common Pitfalls and Solutions

### Pitfall 1: Player Name Mismatch
**Problem:** Callback called but daemon logs "Unknown player"

**Cause:** Player name in -S parameter doesn't match daemon configuration

**Solution:** 
```bash
# Check daemon config
grep -A 5 "players:" /etc/MultiChannelAmpDaemon.yaml

# Ensure exact match:
squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer"
#              ^^^^^^^^^^                                                      ^^^^^^^^^^
#              Must match exactly
```

### Pitfall 2: Missing Player Name in -S
**Problem:** Daemon receives events with wrong player name

**Cause:** Not including player name in -S parameter

**Wrong:**
```bash
squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py"
```

**Correct:**
```bash
squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer"
```

### Pitfall 3: Quote Escaping
**Problem:** Callback not executed or wrong arguments

**Cause:** Incorrect quoting in shell

**Solutions:**
```bash
# Double quotes (recommended)
squeezelite -n wohnzimmer -S "/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer"

# Single quotes (also works)
squeezelite -n wohnzimmer -S '/usr/local/bin/MultiChannelAmpCallback.py wohnzimmer'

# Avoid: No quotes (fails if path has spaces)
squeezelite -n wohnzimmer -S /usr/local/bin/MultiChannelAmpCallback.py wohnzimmer  # WRONG
```

### Pitfall 4: Daemon Not Running
**Problem:** Callback logs "Connection refused"

**Cause:** Daemon not started before Squeezelite

**Solution:**
```bash
# Always start daemon first
sudo systemctl start MultiChannelAmpDaemon.service

# Wait a moment
sleep 2

# Then start Squeezelite instances
systemctl start squeezelite.service
```

## Version History

### 1.0.0 (Current)
- Initial release
- Unix socket communication
- Logging to file
- Error handling for all common cases
- Comprehensive argument validation
- 5-second timeout
- Compatible with MultiChannelAmpDaemon 1.1.0

## Future Enhancements

### Potential Features
1. **Retry Logic:** Retry failed socket connections with exponential backoff
2. **Queue Mode:** Buffer events during daemon unavailability
3. **Status Query:** Optional --status flag to query daemon state
4. **Config File:** Optional config file for socket path and timeout
5. **Metrics:** Export callback statistics for monitoring
6. **Batch Mode:** Accept multiple events in one invocation

### Backward Compatibility
All future versions will maintain compatibility with the current calling convention to ensure existing Squeezelite configurations continue to work.
