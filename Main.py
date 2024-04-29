r"""
To run while not connected to the plotter:
python Main.py --serial_port=none

TODO:
* text
* clean and push code
 """
from absl import app
from absl import flags
import time
import tkinter as tk
import serial
import codecs
import threading
import numpy as np
from matplotlib import pyplot as plt
from scipy.interpolate import splev
from scipy.interpolate import splprep

SERIAL_PORT = flags.DEFINE_string(
    'serial_port', '/dev/ttyUSB0', 
    'Port for plotter. Something like COM9 for Windows. "" or "none" to not connect.')

SPEED = 7000
PEN_UP = (None, None)
BUTTON_FONT = ('Arial', 18)
PEN_UP_GCODE = "G0 Z-5\n"


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


class GCodeFileWriter:
    def __init__(self, filename='output.txt'):
        self.filename = filename
        # Clear file contents
        open(self.filename, 'w').close()

    def send(self, message):
        with open(self.filename, 'a') as f:
            f.write(message)


def fit_bspline(points):
    if len(points) <= 3:
        return points
    x_coords, y_coords = zip(*points)
    tck, u = splprep([x_coords, y_coords], k=3)
    bspline = splev(u[::3], tck)
    return np.array(bspline).T


class DrawingApp:
    def __init__(self, root, gcode_sender):
        self.root = root
        self.root.title("Drawing App")

        self.gcode_sender = gcode_sender

        # Plotter Dimensions in mm
        self.plotter_width = 556
        self.plotter_height = 405

        # Canvas Size in Pixels
        self.canvas_width = self.plotter_width * 2
        self.canvas_height = self.plotter_height * 2

        self.canvas = tk.Canvas(root, bg='white', width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(padx=10, pady=10)

        self.setup()
        self.canvas.bind("<B1-Motion>", self.draw)
        self.canvas.bind("<ButtonRelease-1>", self.reset)

        # TODO: What should happen if currently moving?
        self.canvas.bind("<Control-Button-1>", self.go_to)
        self.canvas.bind("<Command-Button-1>", self.go_to)

        self.sync_mode = False
        self.stop_sync_flag = False
        
        # Button to generate G-code
        self.generate_button = tk.Button(root, text="Generate G-code", command=self.generate_gcode, font=BUTTON_FONT)
        self.generate_button.pack(side=tk.LEFT, padx=(20, 20), pady=10)

        self.toggle_sync_mode_button = tk.Button(root, text="Follow", command=self.toggle_sync_mode, font=BUTTON_FONT)
        self.toggle_sync_mode_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.pen_up_button = tk.Button(root, text="Pen Up", command=self.raise_pen, font=BUTTON_FONT)
        self.pen_up_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.pen_down_button = tk.Button(root, text="Pen Down", command=self.lower_pen, font=BUTTON_FONT)
        self.pen_down_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.clear_canvas_button = tk.Button(root, text="Clear canvas", command=lambda: self.canvas.delete('all'), font=BUTTON_FONT)
        self.clear_canvas_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.reset_button = tk.Button(root, text="Reset Plotter", command=self.reset_plotter, font=BUTTON_FONT)
        self.reset_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        # Button to home the machine
        self.home_button = tk.Button(root, text="Home Plotter", command=self.home_machine, font=BUTTON_FONT)
        self.home_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        self.stop_button = tk.Button(root, text="Stop", command=self.stop_plotter, fg='white', bg='red', font=BUTTON_FONT)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

    def toggle_sync_mode(self):
        if self.sync_mode:
            self.toggle_sync_mode_button.config(relief="raised")
            self.stop_sync_flag = True
            self.sync_mode = False
        else:
            self.toggle_sync_mode_button.config(relief="sunken")
            self.stop_sync_flag = False
            self._send_gcode_thread = threading.Thread(
                target=self.send_code_sync,
                args=(
                ),
                daemon=True,
            )
            self._send_gcode_thread.start()
            self.sync_mode = True

    def home_machine(self):
        self.gcode_sender.send_homing_command()

    def stop_plotter(self):
        self.gcode_sender.send_stop()
        
    def reset_plotter(self):
        self.gcode_sender.reset_fluidnc()
        self.home_machine()

    def raise_pen(self):
        gcode = "G0 Z-5\n"
        self.gcode_sender.send(gcode)
        self.pen_up = True

    def lower_pen(self):
        gcode = "G0 Z5\n"
        self.gcode_sender.send(gcode)
        self.pen_up = False

    def setup(self):
        self.old_x = None
        self.old_y = None
        self.line_width = 8
        self.color = 'light gray'
        self.positions = []
        self.pen_up = True

        self.x_scale = self.plotter_width / self.canvas_width
        self.y_scale = self.plotter_height / self.canvas_height

    def is_within_canvas(self, x, y):
        return 0 <= x <= self.canvas.winfo_width() and 0 <= y <= self.canvas.winfo_height()

    def draw(self, event):
        if self.old_x == event.x and self.old_y == event.y:
            return  # splprep doesn't like repeating points
        if self.old_x and self.old_y and self.is_within_canvas(event.x, event.y):
            self.positions.append((event.x, event.y))

            self.canvas.create_line(self.old_x, self.old_y, event.x, event.y,
                                    width=self.line_width, fill=self.color,
                                    capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36)

        self.old_x = event.x
        self.old_y = event.y

    def go_to(self, event):
        if self.is_within_canvas(event.x, event.y):
            self.raise_pen()
            xScaled = round(self.x_scale * event.x, 1)
            yScaled = round(self.y_scale * (self.canvas_height - event.y), 1)  # Flip the y coordinate
            gcode = f"G1 X{xScaled} Y{yScaled} F{SPEED}\n"
            self.gcode_sender.send(gcode)

    def reset(self, event):
        self.old_x = None
        self.old_y = None
        self.positions.append(PEN_UP)
        
    def plot_bspline(self, bspline):
        plt.plot(*zip(*self.positions), marker='o', linestyle='-', color='blue', label='Mouse Points')
        plt.plot(*zip(*bspline), marker='x', linestyle='-', color='red', label='B Spline')

        plt.legend()
        plt.show()

    def send_code_sync(self):
        self.positions = []
        last_send_time = time.time()
        r = 10
        prev_x = None
        prev_y = None
        x = y = z = -1
        marker_marker = self.canvas.create_oval(
                x-r, self.canvas_height - (y-r),
                x+r, self.canvas_height - (y+r), fill='purple')
        while not self.stop_sync_flag:
            position = self.gcode_sender.get_position()
            if position is not None:
                x, y, z = position
                x /= self.x_scale
                y = self.canvas_height - y / self.y_scale
            self.canvas.moveto(marker_marker, x - r, y - r)

            #-5.0 up; 5.0 down
            if z > 2.5:
                if prev_x is not None and prev_y is not None:
                    self.canvas.create_line(prev_x, prev_y, x, y,
                                    width=self.line_width, fill='black',
                                    capstyle=tk.ROUND)
                prev_x = x
                prev_y = y

            else:
                prev_x = prev_y = None
            if self.positions and self.positions[-1] == PEN_UP:
                self.generate_gcode()
                last_send_time = time.time()
                continue
            if len(self.positions) < 10 and time.time() - last_send_time < 0.2:
                time.sleep(0.05)
                continue
            self.generate_gcode()
            last_send_time = time.time()
        self.canvas.delete(marker_marker)

    def generate_gcode(self):
        positions = self.positions
        self.positions = []
        while positions:
            if positions[0] == PEN_UP:
                gcode = PEN_UP_GCODE
                self.pen_up = True
                if self.gcode_sender:
                    self.gcode_sender.send(gcode)
                del positions[0]
            try:
                pen_up_idx = positions.index(PEN_UP)
            except ValueError:
                pen_up_idx = len(positions)
            spline = fit_bspline(positions[:pen_up_idx])
            positions = positions[pen_up_idx:]
            for x, y in spline:
                # Scale and round the coordinates to a resolution of 0.1mm
                xScaled = round(self.x_scale * x, 1)
                yScaled = round(self.y_scale * (self.canvas_height - y), 1)  # Flip the y coordinate
                gcode = f"G1 X{xScaled} Y{yScaled} F{SPEED}\n"

                if self.pen_up:
                    gcode += "G0 Z5\n"
                    self.pen_up = False

                if self.gcode_sender:
                    self.gcode_sender.send(gcode)


class PreviewApp:
    def __init__(self, root, serial_instance):
        self.root = root
        self.serial_instance = serial_instance
        self.line_width = 2
        self.color = 'black'
        preview_window = tk.Toplevel(self.root)
        preview_window.title("Drawing Preview")
        
        preview_canvas = tk.Canvas(preview_window, bg='white', width=556*2, height=405*2)
        preview_canvas.pack()
        self.preview_canvas = preview_canvas
        self._preview_thread = threading.Thread(
            target=self.draw_preview,
            args=(
            ),
            daemon=True,
        )
        self._preview_thread.start()

    def draw_preview(self):
        last_x, last_y = None, None
        pen_down = False
        r = 4
        while not self.serial_instance.closed:
            line = self.serial_instance.read_until().decode("UTF-8")
            if "G0 Z-5" in line:
                self.preview_canvas.create_oval(last_x-r, last_y-r, last_x+r, last_y+r, fill='red')
                pen_down = False
                continue
            if "G0 Z5" in line:
                self.preview_canvas.create_oval(last_x-r, last_y-r, last_x+r, last_y+r, fill='purple')
                pen_down = True
                continue
            if "G1" in line:
                xScaled = float(line[line.index("X")+1:].split(" ")[0])
                yScaled = float(line[line.index("Y")+1:].split(" ")[0])
                x = xScaled * 2  # TODO: make this x_scale
                y = 405*2 - yScaled * 2  # TODO : configurable
                if pen_down:
                    self.preview_canvas.create_line(last_x, last_y, x, y, width=self.line_width, fill=self.color)

                last_x, last_y = x, y




def main(argv):
    del argv  # unused
    root = tk.Tk()
    if SERIAL_PORT.value and SERIAL_PORT.value.lower() != 'none':
        gcode_sender = GCodeSender(SERIAL_PORT.value)
    else:
        # gcode_sender = GCodeFileWriter()
        gcode_sender = GCodeSender(serial_port='loop://')
        preview_app = PreviewApp(root, gcode_sender.serial_instance)
    app = DrawingApp(root, gcode_sender)
    root.mainloop()

if __name__ == '__main__':
    app.run(main)
