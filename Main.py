r"""
To run while not connected to the plotter:
python Main.py --serial_port=none
 """
from absl import app
from absl import flags
import time
import tkinter as tk
from collections import deque
import math
import serial
import codecs
import numpy as np
from matplotlib import pyplot as plt
from scipy.interpolate import splev
from scipy.interpolate import splprep

SERIAL_PORT = flags.DEFINE_string(
    'serial_port', '/dev/ttyUSB0', 
    'Port for plotter. Something like COM9 for Windows. "" or "none" to not connect.')

# Follow along as the user draws
SYNC_MODE = True
SPEED = 7000
SEND_FREQUENCY = 20

class GCodeSender:
    def __init__(self, serial_port):
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

    def send(self, message):
        for c in message:
            self.serial_instance.write(self.tx_encoder.encode(c))
            
    def send_homing_command(self):
        print('Homing')
        self.send('$H\n')

    def reset_fluidnc(self):
        """Pulse the reset line for FluidNC"""
        print("Resetting FluidNC")
        self.serial_instance.rts = True
        self.serial_instance.dtr = False
        time.sleep(1)
        self.serial_instance.rts = False
        # TODO: progress bar
        time.sleep(12)

    def __del__(self):
        if self.serial_instance:
            self.serial_instance.close()


def fit_bspline(points):
    x_coords, y_coords = zip(*points)
    # TODO: Clean this up. (removing duplicate points)
    points = np.array(points)[np.array(np.where(np.abs(np.diff(x_coords)) + np.abs(np.diff(y_coords)) > 0))].squeeze()
    x_coords = points[:, 0]
    y_coords = points[:, 1]
    tck, u = splprep([x_coords, y_coords], k=3)
    bspline = splev(u[::5], tck)
    return np.array(bspline).T

class DrawingApp:
    def __init__(self, root, gcode_sender):
        self.root = root
        self.root.title("Drawing App")

        self.gcode_sender = gcode_sender
        self.sync_mode = SYNC_MODE

        # Plotter Dimensions in mm
        self.plotter_width = 570
        self.plotter_height = 450

        # Canvas Size in Pixels
        self.canvas_width = self.plotter_width * 2
        self.canvas_height = self.plotter_height * 2

        self.canvas = tk.Canvas(root, bg='white', width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(padx=10, pady=10)

        self.setup()
        self.canvas.bind("<B1-Motion>", self.draw)
        self.canvas.bind("<ButtonRelease-1>", self.reset)
        
        # Button to home the machine
        self.home_button = tk.Button(root, text="Home Machine", command=self.home_machine)
        self.home_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        # Button to generate G-code
        self.generate_button = tk.Button(root, text="Generate G-code", command=self.generate_gcode)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        # Button to preview drawing for testing
        self.preview_button = tk.Button(root, text="Preview Drawing", command=self.preview_drawing)
        self.preview_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.reset_button = tk.Button(root, text="Reset Plotter", command=self.reset_plotter)
        self.reset_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

    def home_machine(self):
        self.gcode_sender.send_homing_command()
        
    def reset_plotter(self):
        self.gcode_sender.reset_fluidnc()
        self.home_machine()

    def setup(self):
        self.old_x = None
        self.old_y = None
        self.line_width = 2
        self.color = 'black'
        self.positions = deque()  # Using deque for storing positions

        # Scaling factors
        self.x_scale = self.plotter_width / self.canvas_width
        self.y_scale = self.plotter_height / self.canvas_height

    def is_within_canvas(self, x, y):
        return 0 <= x <= self.canvas.winfo_width() and 0 <= y <= self.canvas.winfo_height()

    #Updated Draw Method to deal with polling issue
    def draw(self, event):
        if self.old_x == event.x and self.old_y == event.y:
            return  # splprep doesn't like repeating points
        if self.old_x and self.old_y and self.is_within_canvas(event.x, event.y):
            # Interpolate points between the last position and the current position
            self.interpolate_and_store(self.old_x, self.old_y, event.x, event.y)

            # Draw line
            self.canvas.create_line(self.old_x, self.old_y, event.x, event.y,
                                    width=self.line_width, fill=self.color,
                                    capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36)
            if self.sync_mode and len(self.positions) > SEND_FREQUENCY:
                self.generate_gcode()

        self.old_x = event.x
        self.old_y = event.y

    def interpolate_and_store(self, x1, y1, x2, y2):
        distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        
        # Define how many points based on the distance
        points_count = max(int(distance / 2), 1)  # Ensure at least one point is added
        # TODO: Maybe remove interpolation and explicitly mark pen up and pen down

        for i in range(1, points_count + 1):
            # Linear interpolation
            x = x1 + (x2 - x1) * i / points_count
            y = y1 + (y2 - y1) * i / points_count
            self.positions.append((x, y))

    def reset(self, event):
        self.old_x = None
        self.old_y = None
        
    def preview_drawing(self):
        bspline = fit_bspline(self.positions)
        self._preview_drawing(bspline)
        # self.plot_bspline()

    def plot_bspline(self, bspline):
        plt.plot(*zip(*self.positions), marker='o', linestyle='-', color='blue', label='Mouse Points')
        plt.plot(*zip(*bspline), marker='x', linestyle='-', color='red', label='B Spline')

        plt.legend()
        plt.show()

    def _preview_drawing(self, positions):
        preview_window = tk.Toplevel(self.root)
        preview_window.title("Drawing Preview")
        
        preview_canvas = tk.Canvas(preview_window, bg='white', width=self.canvas_width, height=self.canvas_height)
        preview_canvas.pack()

        last_x, last_y = None, None
        deadzone = 10

        for x, y in positions:

            if last_x is not None and last_y is not None:
                distance = math.sqrt((x - last_x) ** 2 + (y - last_y) ** 2)
                if distance > deadzone:
                    # Starting a new stroke, so lift the pen
                    last_x, last_y = None, None  # Reset last positions to create a gap

            if last_x is not None and last_y is not None:
                # Draw line for continuous stroke
                preview_canvas.create_line(last_x, last_y, x, y, width=self.line_width, fill=self.color)
            else:
                # Mark the start of a new stroke
                preview_canvas.create_oval(x-2, y-2, x+2, y+2, fill=self.color)

            last_x, last_y = x, y

    def generate_gcode(self, filename='output.txt', deadzone=10):
        start = time.time()
        with open(filename, 'w') as file:
            last_x, last_y = None, None
            pen_up = True

            positions = fit_bspline(self.positions)
            for x, y in positions:

                if last_x is not None and last_y is not None:
                    # Calculate distance to previous point
                    distance = math.sqrt((x - last_x) ** 2 + (y - last_y) ** 2)

                    if distance > deadzone and not pen_up:
                        # Pen up command
                        file.write("M0 ;Pen up\n")
                        pen_up = True
                
                # Scale and round the coordinates to a resolution of 0.1mm
                xScaled = round(self.x_scale * x, 1)
                yScaled = round(self.y_scale * (self.canvas_height - y), 1)  # Flip the y coordinate

                if pen_up:
                    # Move to new position with pen up
                    file.write(f"G0 X{xScaled} Y{yScaled}\n")
                    gcode = f"G1 X{xScaled} Y{yScaled} F{SPEED}\n"
                    # Pen down command
                    file.write("M1 ;Pen down\n")
                    pen_up = False
                else:
                    # Move to new position with pen down
                    file.write(f"G1 X{xScaled} Y{yScaled}\n")
                    gcode = f"G1 X{xScaled} Y{yScaled} F{SPEED}\n"
                if self.gcode_sender:
                    self.gcode_sender.send(gcode)

                last_x, last_y = x, y
            self.positions = deque()

            # Ensure pen is up at the end
            file.write("M5 ;Pen up\n")

        print(f"G-code written to {filename} in {time.time() - start} s")

def main(argv):
    del argv  # unused
    root = tk.Tk()
    if SERIAL_PORT.value and SERIAL_PORT.value.lower() != 'none':
        gcode_sender = GCodeSender(SERIAL_PORT.value)
    else:
        gcode_sender = None
    app = DrawingApp(root, gcode_sender)
    root.mainloop()

if __name__ == '__main__':
    app.run(main)
