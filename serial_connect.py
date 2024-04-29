"""
Simple script for testing serial control of plotter.

x is small stage
g90 absolute
g91 relative
x: 0-500
y: 0-440
"""
import serial
import codecs

# jog x 10mm at slow feedrate
# message = '$j=g91 g21 x10 f500\n'
message = '?'
serial_instance = serial.serial_for_url(
    '/dev/ttyUSB0', baudrate=115200, bytesize=8, parity='N', 
    stopbits=1, timeout=None, xonxoff=False, rtscts=False, dsrdtr=False)
encoding = 'UTF-8'
errors = 'replace'
tx_encoder = codecs.getincrementalencoder(encoding)(errors)
for c in message:
    serial_instance.write(tx_encoder.encode(c))
line = serial_instance.read_until().decode("UTF-8")
print(line)
import ipdb; ipdb.set_trace()
serial_instance.close()