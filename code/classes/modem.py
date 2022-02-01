#!/usr/bin/env python
import threading
import itertools
import sys
import serial
import time
import yaml
from datetime import datetime

# Parse config file
config_file = "/home/pi/nav/config.yaml"
config = yaml.safe_load(open(config_file))

# Get network settings
settings = {
    'sound_speed'   : float(config['settings']['sound_speed']),
    'rate'          : float(config['settings']['rate']),
    'reply_timeout' : float(config['settings']['reply_timeout']),
}

class Modem:
    """A class for communications with Delphis Subsea Modems"""

    #======================================================
    # Process config file
    #======================================================
    def __init__(self, mode=None, args=None):

        # Open serial connection
        self.ser = serial.Serial(
            port='/dev/ttyUSB0',
            baudrate = 9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        )

        # Verify modem status
        status = self.status()
        self.address = status['address']

        # Fall back to mode in config file if mode not set
        self.mode = mode or config['modems'][self.address]['mode']
        self.args = args

        # Define active and passive modems
        self.active_modems = [int(m) for m in config['modems'].keys() \
                              if config['modems'][m]['mode']=='active']
        self.passive_modems = [int(m) for m in config['modems'].keys() \
                               if config['modems'][m]['mode']=='passive']

        # Initialize dictionary for location of passive modems
        self.locs = {m:{'x': config['modems'][m]['x'],
                        'y': config['modems'][m]['y']}
                     for m in self.passive_modems}

    #======================================================
    # Low-level modem commands
    #======================================================
    def send_and_wait(self, cmd=None, n=1, prefix=None):
        "Optionally send a command and wait for the nth response"
        t0 = time.time()
        c = 0
        while c<n and time.time() - t0 < settings['reply_timeout']:
            # Send command until at least 1 response is recieved,
            # then keep listening until nth response.
            if cmd and c==0:
                self.ser.write(cmd.encode())

            # If we get a response with the right prefix, increment the counter
            response = self.ser.readline().decode().strip()
            if response and (not prefix or response[1] in prefix):
                c+=1
            time.sleep(settings['rate'])
        return response

    def status(self):
        "Query node address and voltage"
        cmd = "$?"
        response = self.send_and_wait(cmd=cmd,prefix="A")
        return self.parse_msg(response, stdout=True)

    def set_address(self, address):
        "Set node address"
        cmd = "$A%03d" % (address)
        response = self.send_and_wait(cmd)
        return self.parse_msg(response, stdout=True)

    def broadcast(self, message):
        "Send message to all units in range"
        cmd = "$B%02d%s" % (len(message), message)
        response = self.send_and_wait(cmd=cmd)
        print("Broadcast: {}".format(message))

    def unicast(self, message, target):
        "Send message to target unit (specified by 3-digit integer)"
        cmd = "$U%03d%02d%s" % (target, len(message), message)
        response = self.send_and_wait(cmd=cmd)
        print("Unicast to {}: {}".format(target, message))

    def ping(self, target, wait=False):
        "Send ping to target unit"
        cmd = "$P%03d" % (target)
        if wait:
            response = self.send_and_wait(cmd=cmd,prefix=["P","R"],n=2)
            print(response)
            # return self.parse_msg(response, stdout=True);
        else:
            self.ser.write(cmd.encode())
            return []

    #======================================================
    # Processing threads
    #======================================================

    def ping_passive_beacons(self):
        "Loop over passive beacons and record distances"
        t0 = time.time() - settings['rate']
        for target in itertools.cycle(self.passive_modems):
            while time.time() - t0 <= settings['rate']:
                time.sleep(0.005)
            msg = self.ping(target,wait=False)
            t0 = time.time()

    def report_all(self):
        "Parse all incoming messages"
        while self.ser.is_open:
            line = self.ser.readline().decode().strip()
            msg = self.parse_msg(line, stdout=True)

    def timer(self):
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
        lock = threading.Lock()
        report_thread = threading.Thread(target = self.report_all)
        ping_thread = threading.Thread(target = self.ping_passive_beacons)
        timer_thread = threading.Thread(target = self.timer)

        # Set node address
        if mode == "set":
            address = int(self.args[0])
            self.set_address(address)

        # Active mode:
        # - Loop through passive beacons in sequence
        # - Parse all incoming messages
        elif mode == "active":
            ping_thread.start()
            report_thread.start()

        # Timer mode:
        # - Broadcast current time at specified rate, unicast if target specified
        elif mode == "timer":
            timer_thread.start()

        # Report mode:
        # - Parse all incoming messages
        elif mode == "report":
            report_thread.start()


    def parse_msg(self, msg_str, stdout=False):
        if msg_str:

            # Get message prefix
            msg = {'type': msg_str[1]}

            # Status: #AxxxVyyyyy (in response to $?)
            #      or #Axxx       (in response to $Axxx)
            if msg['type'] == "A":
                msg['address'] = int(msg_str[2:5]) # xxx
                if len(msg_str) > 5:
                    msg['voltage'] = float(msg_str[6:])*15/65536  # yyyyy...
                    if stdout:
                        print("Modem ID: %s; voltage: %.2fmV" % \
                              (msg['address'],msg['voltage']))
                else:
                    if stdout:
                        print("Modem ID: set to %03d" % msg['address'])

            # Broadcast: #Bxxxnnddd...
            elif msg['type'] == "B":
                msg['src'] = int(msg_str[2:5]) # xxx
                msg['len'] = int(msg_str[5:7]) # nn
                msg['str'] = msg_str[7:]  # ddd...
                if stdout:
                    print("Broadcast from {}: {}".format(msg['src'], msg['str']))

            # Unicast: #Unnddd...
            elif msg['type'] == "U":
                msg['src'] = []
                msg['len'] = int(msg_str[2:4]) # nn
                msg['str'] = msg_str[4:]  # ddd...
                if stdout:
                    print("Unicast received: {}".format(msg['str']))

            # Range: RxxxTyyyyy
            elif msg['type'] == "R":
                msg['src'] = int(msg_str[2:5])
                msg['range'] = settings['sound_speed'] * 3.125e-5 * float(msg_str[6:11]);
                if stdout:
                    print("%03d %.4fm" % (msg['src'], msg['range']))
                return msg

            else:
                msg['str'] = msg_str

            return msg

        else:
            return []
