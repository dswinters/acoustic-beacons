#!/usr/bin/env bash
sudo cp beacons.service /etc/systemd/system/beacons.service
sudo cp beacons.conf /etc/rsyslog.d/beacons.conf
sudo systemctl daemon-reload
sudo systemctl restart rsyslog
sudo systemctl enable beacons
