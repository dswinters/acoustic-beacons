#!/usr/bin/env bash

local_dir=$(pwd)
remote_dir="/home/pi/nav"

for i in 0{1..2}; do
  host="navbeacon$i"
  echo "Deploying to $host"
  rsync -ra --partial-dir=/tmp --files-from=deploy_list.txt "$local_dir" "$host:$remote_dir"
done
