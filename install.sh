#!/usr/bin/env bash

# systemd service
sudo cp system/beacons.service /etc/systemd/system/beacons.service

# rsyslog configuration
sudo cp system/beacons.conf /etc/rsyslog.d/beacons.conf

# udev rules for renaming serial ports
sudo cp system/10-beacon.rules /etc/udev/rules.d/10-beacon.rules

# enable & restart everything
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl daemon-reload
sudo systemctl restart rsyslog
sudo systemctl enable beacons
