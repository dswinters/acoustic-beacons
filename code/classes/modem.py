#!/usr/bin/env python
from threading import Thread
import itertools
import sys
import serial
import time
import yaml
import numpy as np
from datetime import datetime
from classes.mlat_solver import Mlat

# Parse config file
config_file = "/home/pi/nav/config.yaml"
config = yaml.safe_load(open(config_file))

# Get network settings
settings = {
    'sound_speed'    : float(config['settings']['sound_speed']),
    'repeat_rate'    : float(config['settings']['repeat_rate']),
    'range_rate'     : float(config['settings']['range_rate']),
    'broadcast_rate' : float(config['settings']['broadcast_rate']),
    'reply_timeout'  : float(config['settings']['reply_timeout']),
    'randomize'      : float(config['settings']['randomize']),
}

class Modem:
    """A class for communications with Delphis Subsea Modems"""

    #======================================================
    # Process config file
    #======================================================
    def __init__(self, mode=None, args=None):

        # Open serial connection to modem
        self.ser = serial.Serial(
            port='/dev/ttyUSB0',
            baudrate = 9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        )

        # # TODO Open serial connection to GPS
        # self.ser_gps = serial.Serial(
        #     port='/dev/ttyAMA0',
        #     baudrate = 9600,
        #     bytesize=serial.EIGHTBITS,
        #     parity=serial.PARITY_NONE,
        #     stopbits=serial.STOPBITS_ONE,
        #     timeout=0.1
        # )

        # Verify modem status
        status_msg = self.status()
        self.address = status_msg['src']
        print("Connected to modem %d, voltage: %.2fV" % (self.address,status_msg['voltage']))

        # Fall back to mode in config file if mode not set
        self.mode = mode or config['modems'][self.address]['mode']
        print("Starting in %s mode" % self.mode)
        self.args = args

        # Define active and passive modems
        self.active_modems = [int(m) for m in config['modems'].keys() \
                              if config['modems'][m]['mode']=='active']
        self.passive_modems = [int(m) for m in config['modems'].keys() \
                               if config['modems'][m]['mode']=='passive']

        # Initialize multilateration solver
        self.mlat = Mlat(config)
        if config['settings']['coords'] == 'local':
            for m in self.passive_modems:
                x = config['modems'][m]['x']
                y = config['modems'][m]['y']
                lat,lon = self.mlat.local2gps(x,y)
                config['modems'][m]['lat'] = lat
                config['modems'][m]['lon'] = lon

        # Initialize dictionaries for locations & distances of passive beacons
        self.locs = {m:{'lat': config['modems'][m]['lat'],
                        'lon': config['modems'][m]['lon']}
                     for m in self.passive_modems}
        self.dists = {m:None for m in self.passive_modems}

        # Get initial position from config file
        self.lat = None
        self.lon = None
        if self.mode == "passive":
            self.lat = config['modems'][self.address]['lat']
            self.lon = config['modems'][self.address]['lon']

    #======================================================
    # Low-level modem commands
    #======================================================
    def send(self, cmd=None, wait=False, n=1, prefix=None):
        "Send a command, optionally wait for the Nth response"

        # If a command is specified and wait==False, send the command and
        # immediately return.
        if cmd and not wait:
            self.ser.write(cmd.encode())
            return None

        # If wait==True, then:
        # - Send the command (if a command is given)
        # - Wait for the nth response with the desired prefix(es)
        #   - If no prefix(es) is specified, wait for nth response with any prefix.
        elif wait:
            t0 = time.time()
            c = 0
            while c<n and time.time() - t0 < settings['reply_timeout']:
                # Send command until at least 1 response is recieved,
                # then keep listening until nth response.
                if cmd and c==0:
                    self.ser.write(cmd.encode())

                # If we get a response with the right prefix, increment the counter
                response = self.ser.readline().decode().strip()
                if response and ((not prefix) or (response[1] in prefix)):
                    c+=1
                time.sleep(settings['repeat_rate'])
            return parse_message(response)

    def status(self):
        "Query node address and voltage"
        cmd = "$?"
        return self.send(cmd=cmd, wait=True, prefix="A")

    def set_address(self, address):
        "Set node address"
        cmd = "$A%03d" % (address)
        return self.send(cmd=cmd, wait=True, prefix="A")

    def broadcast(self, message, wait=False):
        "Send message to all units in range"
        cmd = "$B%02d%s" % (len(message), message)
        return self.send(cmd=cmd, wait=wait)

    def unicast(self, message, target, wait=False):
        "Send message to target unit (specified by 3-digit integer)"
        cmd = "$U%03d%02d%s" % (target, len(message), message)
        return self.send(cmd=cmd, wait=wait)

    def ping(self, target, wait=False):
        "Send range ping to target unit"
        cmd = "$P%03d" % (target)
        return self.send(cmd=cmd,prefix=["P","R"],n=2,wait=wait)

    #======================================================
    # Processing threads
    #======================================================
    # We should be fine to run any number of threads as long as:
    # - No two threads try to write to the same serial port at the same time
    # - No two threads try to read from the same serial port at the same time
    #
    # I've tried to set this up so any given thread only reads or only writes,
    # and only to one serial port.

    def active_ping(self):
        "Cyclically loop over passive beacons and send ranging pings"
        # Writes to acoustic modem serial port
        t0 = time.time() - settings['range_rate']
        for target in itertools.cycle(self.passive_modems):
            while time.time() - t0 <= settings['range_rate']:
                time.sleep(0.005)
            self.ping(target,wait=False)
            t0 = time.time() + rand()

    def active_listen(self):
        "Parse ranging returns and broadcasts, update positions & distances"
        while self.ser.is_open:
            msg_str = self.ser.readline().decode().strip()
            msg = parse_message(msg_str)

            # Update position or distance from passive beacon
            if msg:
                if msg['type'] == 'broadcast':
                    if is_hex(msg['str']):
                        lat,lon = decode_ll(msg['str'])
                        self.locs[msg['src']]['lat'] = lat
                        self.locs[msg['src']]['lon'] = lon
                        print("%d is at %.5fN,%.5fE" % (msg['src'],lat,lon),flush=True)
                elif msg['type'] == 'range':
                    self.dists[msg['src']] = msg['range']
                    print("%.2f m from %d" % (msg['range'], msg['src']),flush=True)

                # Pass positions & distances to multilateration solver
                self.mlat.solve(self.locs,self.dists)

    def passive_gps(self):
        "Parse all incoming GPS messages and update position"
        # Reads from GPS serial port
        while self.ser_gps.is_open:
            msg_str = self.ser_gps.readline().decode().strip()
            # TODO: parse GPS messages and assign lat and lon
            # self.lat = ...
            # self.lon = ...

    def passive_broadcast(self):
        "Periodically broadcast current position"
        while self.ser.is_open:
            msg = encode_decimal_deg(self.lat) + encode_decimal_deg(self.lon)
            self.broadcast(msg)
            time.sleep(settings['broadcast_rate'] + rand())

    def debug_report(self):
        "Parse all incoming modem messages"
        # Reads from acoustic modem serial port
        while self.ser.is_open:
            msg_str = self.ser.readline().decode().strip()
            msg = parse_message(msg_str)
            if msg:
                print(msg)

    def debug_timer(self):
        "Periodically broadcast the current time"
        period = float(self.args[0]) - settings['rate']
        target = len(self.args)>1 and int(self.args[1]) or None
        while self.ser.is_open:
            current_time = datetime.now().strftime("%H:%M:%S")
            if target:
                self.unicast(current_time, target)
            else:
                self.broadcast(current_time)
            time.sleep(period)

    #======================================================
    # Main loop
    #======================================================
    def run(self, mode):

        # Set address and exit if in "set" mode
        if mode == "set":
            address = int(self.args[0])
            self.set_address(address)

        # Define threads, but don't start any
        ping_thread = Thread(target = self.active_ping)
        listen_thread = Thread(target = self.active_listen)
        gps_thread = Thread(target = self.passive_gps)
        broadcast_thread = Thread(target = self.passive_broadcast)

        # Threads for debugging
        report_thread = Thread(target = self.debug_report)
        timer_thread = Thread(target = self.debug_timer)

        if mode == "active":
            ping_thread.start()
            listen_thread.start()

        elif mode == "passive":
            broadcast_thread.start()

        elif mode == "timer":
            timer_thread.start()
            report_thread.start()

        elif mode == "report":
            report_thread.start()

#=========================================================================
# Helper functions
#=========================================================================

def parse_message(msg_str):
    "Parse a raw message string and return a useful structure"
    if not msg_str:
        return None

    # Get message prefix and initialize output
    prefix = msg_str[1];
    msg = {}

    # Status: #AxxxVyyyyy in response to "$?" (query status)
    #      or #Axxx       in response to "$Axxx" (set address)
    if prefix == "A":
        msg['type'] = "status"
        msg['src'] = int(msg_str[2:5]) # xxx
        if len(msg_str) > 5:
            msg['voltage'] = float(msg_str[6:])*15/65536  # yyyyy...
        else:
            msg['voltage'] = None

    # Broadcast: #Bxxxnnddd... (broadcast recieved)
    #            #Bnn          (self broadcast acknowledge)
    elif prefix == "B":
        if len(msg_str) > 4:
            msg['type'] = "broadcast"
            msg['src'] = int(msg_str[2:5]) # xxx
            msg['str'] = msg_str[7:]  # ddd...
        else:
            msg['type'] = "broadcast_ack"
            msg['len'] = int(msg_str[2:])

    # Unicast: #Unnddd...
    elif prefix == "U":
        msg['type'] = "unicast"
        msg['src'] = None
        msg['str'] = msg_str[4:]  # ddd...

    # Range: RxxxTyyyyy
    elif prefix == "R":
        msg['type'] = "range"
        msg['src'] = int(msg_str[2:5])
        msg['range'] = settings['sound_speed'] * 3.125e-5 * float(msg_str[6:11]);

    # Note: Other message types are possible, but we don't currently use any of
    #       them. Return None if we encounter these.
    else:
        return None

    # Return message structure
    return msg

def encode_decimal_deg(deg):
    "Encode decimal lat or lon to hexidecimal degrees, minutes, seconds"
    # Output string looks like:  [DD] [MM] [SSS]  [N]
    #                              |    |    |     |
    #                           Degrees | Seconds  |
    #                                 Minutes    1 if negative
    neg = deg < 0
    deg = abs(deg)
    mins = (deg-np.floor(deg))*60
    secs = (mins-np.floor(mins))*int('fff',16)
    return "%02x%02x%03x%1x" % (int(np.floor(deg)), int(np.floor(mins)), int(np.floor(secs)), neg)

def decode_hex_dms(dms):
    "Decode hexidecimal degrees,mins,secs to decimal degrees"
    degs = int(dms[0:2],16)
    mins = int(dms[2:4],16)
    secs = int(dms[4:7],16)*60/int('fff',16)
    neg = bool(int(dms[7]))
    dec = degs + mins/60 + secs/60**2
    return neg and -1*dec or dec

def encode_ll(lat,lon):
    return encode_decimal_deg(lat) + encode_decimal_deg(lon)

def decode_ll(hex_str):
    return decode_hex_dms(hex_str[0:8]), decode_hex_dms(hex_str[8:])

def is_hex(s):
    try:
        int(s, 16)
        return True
    except ValueError:
        return False

def rand():
    return settings['randomize'] * np.random.random()
