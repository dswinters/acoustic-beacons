#!/usr/bin/env bash

mount_dir=$HOME/network-mounts
remote_dir="/home/pi/nav"

for i in 0{1..2}; do

  # Name should match an entry in .ssh/config
  name="navbeacon$i"
  echo "Deploying to $name"

  # Copy code directory recursively
  local=code
  remote=pi@$name:/$remote_dir
  scp -r $local $remote && echo "  - copied $local to $remote"

  # Copy config file
  local=config.yaml
  remote=pi@$name:/$remote_dir/config.yaml
  scp $local $remote && echo "  - copied $local to $remote"

  local=beacons.service
  remote=pi@$name:/$remote_dir/beacons.service
  scp $local $remote && echo "  - copied $local to $remote"

  local=beacons.conf
  remote=pi@$name:/$remote_dir/beacons.conf
  scp $local $remote && echo "  - copied $local to $remote"

  local=install.sh
  remote=pi@$name:/$remote_dir/install.sh
  scp $local $remote && echo "  - copied $local to $remote"

done
