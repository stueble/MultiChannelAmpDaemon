# Description
Systemd service script to start ```MultiChannelAmpDaemon.py```

## Installation

```bash
# 1. Copy service file
sudo cp MultiChannelAmpDaemon.service /etc/systemd/system/

# 2. Reload systemd
sudo systemctl daemon-reload

# 3. Ebnable auto start during boot
sudo systemctl enable MultiChannelAmpDaemon.service

# 4. Start service
sudo systemctl start MultiChannelAmpDaemon.service
```

## Usage

```bash
# Check status
sudo systemctl status MultiChannelAmpDaemon.service

# show logs
sudo journalctl -u MultiChannelAmpDaemon.service -f

# Stop service
sudo systemctl stop MultiChannelAmpDaemon.service

# Restart service
sudo systemctl restart MultiChannelAmpDaemon.service

# Disable auto start
sudo systemctl disable MultiChannelAmpDaemon.service
```
