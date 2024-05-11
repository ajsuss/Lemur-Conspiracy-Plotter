"""Handles serial connection to FluidNC running on plotter."""

import codecs
import serial
import time

class GCodeSender:
    def __init__(self, serial_port, allow_position_query=True):
        # if connection fails, want serial_instance = None so del works
        self.serial_instance = None
        self.serial_instance = serial.serial_for_url(
            serial_port, baudrate=115200, bytesize=8, parity='N', 
            stopbits=1, timeout=None, xonxoff=False, rtscts=False, dsrdtr=False)
        encoding = 'UTF-8'
        errors = 'replace'
        self.tx_encoder = codecs.getincrementalencoder(encoding)(errors)
        # G90: absolute position, G21: millimeters
        self.send('G90 G21 \n')
        self.allow_position_query = allow_position_query

    def send(self, message):
        for c in message:
            self.serial_instance.write(self.tx_encoder.encode(c))
            
    def send_homing_command(self):
        print('Homing')
        self.send('$H\n')

    def send_stop(self):
        self.send('!')

    def reset_fluidnc(self):
        """Pulse the reset line for FluidNC"""
        print("Resetting FluidNC")
        self.serial_instance.rts = True
        self.serial_instance.dtr = False
        time.sleep(1)
        self.serial_instance.rts = False
        # TODO: progress bar
        time.sleep(12)

    def get_position(self):
        if not self.allow_position_query:
            return None
        self.serial_instance.reset_input_buffer()
        self.send('?')
        line = self.serial_instance.read_until().decode("UTF-8").strip()
        if not (line.startswith('<') and line.endswith('>')):
            return None
        try:
            position_str = line.split('|')[1].split(':')[1]
        except IndexError:
            return None
        position = [float(x) for x in position_str.split(',')]
        if len(position) != 3:
            return None
        return position

    def __del__(self):
        if self.serial_instance:
            self.serial_instance.close()

