r"""
To run while not connected to the plotter:
python Main.py --serial_port=none

TODO:
 """
from absl import app
from absl import flags
import time
import tkinter as tk
import customtkinter
import serial
import codecs
import threading
import numpy as np
from matplotlib import pyplot as plt
from scipy.interpolate import splev
from scipy.interpolate import splprep
import os
from PIL import Image
import font_constants

SERIAL_PORT = flags.DEFINE_string(
    'serial_port', '/dev/ttyUSB0', 
    'Port for plotter. Something like COM9 for Windows. "" or "none" to not connect.')

SPEED = 7000
PEN_UP = (None, None)
BUTTON_FONT = ('Arial', 18)
LABEL_FONT = ('Arial', 12)
PEN_UP_GCODE = "G0 Z-5\n"

customtkinter.set_appearance_mode("dark")  # Modes: system (default), light, dark
customtkinter.set_default_color_theme("blue")  # Themes: blue (default), dark-blue, green
customtkinter.set_widget_scaling(2)  # widget dimensions and text size
# customtkinter.set_window_scaling(2)  # window geometry dimensions
customtkinter.DrawEngine.preferred_drawing_method = "circle_shapes"


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
        # print('sending', message)
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
        # TODO: Make this more elegant?
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
        self.root.title("Lemur Conspiracy Plotter")

        self.gcode_sender = gcode_sender

        # Plotter Dimensions in mm
        self.plotter_width = 556
        self.plotter_height = 405

        left_frame = tk.Frame(root, bg=root.cget('bg'))
        left_frame.pack(side='left',  fill='both',  padx=10,  pady=5,  expand=True)

        right_frame = tk.Frame(root, width=650, bg=root.cget('bg'))
        right_frame.grid_propagate(0)
        right_frame.pack(side='right',  fill='both',  padx=10,  pady=5,  expand=True)
        # Canvas Size in Pixels
        self.canvas_width = self.plotter_width * 3
        self.canvas_height = self.plotter_height * 3

        self.canvas = tk.Canvas(left_frame, bg='white', width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(padx=10, pady=10)

        self.setup()
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.draw)
        self.canvas.bind("<ButtonRelease-1>", self.reset)

        # TODO: What should happen if currently moving?
        self.canvas.bind("<Control-Button-1>", self.go_to)
        self.canvas.bind("<Command-Button-1>", self.go_to)

        self.sync_mode = False
        self.stop_sync_flag = False

        def load_image(filename, size=(20, 20)):
            image_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images")
            return customtkinter.CTkImage(Image.open(os.path.join(image_dir, filename)), size=size)

        def add_button(text, command, image=None, frame=right_frame, pack_side='top'):
            button = customtkinter.CTkButton(
                frame, 
                corner_radius=4, 
                text=text, 
                image=image, 
                command=command, 
                font=BUTTON_FONT)
            button.pack(side=pack_side, padx=(20, 20), pady=10, anchor='w', fill='x', expand=True)
            return button

        stop_button = add_button("Stop", self.stop_plotter, image=load_image("stop_96.png"))
        stop_button.configure(text_color='white', fg_color='firebrick1', hover_color='firebrick4')
        # TODO: E-stopped indicator?

        home_image = load_image("home_light.png")
        add_button("Home plotter", self.home_machine, home_image)
        add_button("Reset plotter", self.reset_plotter, load_image("reset-64.png"))

        pen_up_down_frame = tk.Frame(right_frame, bg=root.cget('bg'))
        pen_up_down_frame.pack(fill='x', expand=True)
        add_button("Pen up", self.raise_pen, frame=pen_up_down_frame, pack_side="left")
        add_button("Pen down", self.lower_pen, frame=pen_up_down_frame, pack_side="right")

        add_button("Draw!", self.send_text_and_drawings)
        self.toggle_sync_mode_button = customtkinter.CTkSwitch(
            right_frame, text="Draw as I draw", command=self.toggle_sync_mode, font=BUTTON_FONT)
        self.toggle_sync_mode_button.pack(padx=(20, 20), pady=10, anchor='w')

        add_button("Clear canvas", lambda: self.canvas.delete('all'))
        self.straight_line_var = customtkinter.StringVar(value="")
        self.straight_segment = None
        switch = customtkinter.CTkSwitch(right_frame, text="Draw straight lines",
                                         font=BUTTON_FONT,
                                 variable=self.straight_line_var, onvalue="on", offvalue="")
        switch.pack(padx=(20, 20), pady=10, anchor='w')
        self.text_positions = []
        self.text_positions_anchored = []
        self.text_segments = []
        self.text_left_corner = (100, self.canvas_height // 2)
        self.canvas.bind("<Shift-Button-1>", self.set_text_left_corner)
        self.canvas.bind("<Shift-B1-Motion>", self.set_text_left_corner)
        
        self.entry = customtkinter.CTkEntry(right_frame, font=BUTTON_FONT,
                                            placeholder_text="Text to write")
        self.entry.pack(padx=(20, 20), pady=10, anchor='w', fill='x', expand=True)
        self.entry.bind("<Return>", self.write)

        text_options_frame = tk.Frame(right_frame, bg=root.cget('bg'))
        text_options_frame.pack(fill='x', expand=True)
        label = customtkinter.CTkLabel(master=text_options_frame, text="Anchor text down", font=LABEL_FONT)
        label.pack(side="top", anchor="w", padx=(20, 0), pady=(0, 0))
        add_button("", self.anchor_text, load_image("anchor-96.png"), frame=text_options_frame, pack_side="left")
        self.font_size_var = customtkinter.StringVar(value="Font size (1)")
        optionmenu = customtkinter.CTkOptionMenu(text_options_frame,values=["font size (1)"] + [str(x) for x in (range(2, 11))],
                                         command=self.write,
                                         font=BUTTON_FONT,
                                         dropdown_font=BUTTON_FONT,
                                         variable=self.font_size_var)
        optionmenu.pack(side='right', padx=(20, 20), pady=10, anchor='w')

    def pen_up_down(self, value):
        if value == "Pen Up":
            self.raise_pen()
        else:
            self.lower_pen()
        self.segmented_button.set(None)

    def anchor_text(self):
        self.text_positions_anchored.extend(self.text_positions)
        self.text_positions = []
        self.text_segments = []
        self.entry.delete(0, tk.END)

    def set_text_left_corner(self, event):
        if not self.is_within_canvas(event.x, event.y):
            return
        self.text_left_corner = (event.x, event.y)
        self.write()

    def write(self, entry=None):
        text = self.entry.get()
        for segment in self.text_segments:
            self.canvas.delete(segment)
        self.text_segments = []
        self.text_positions = []
        left_corner = self.text_left_corner
        scale_str = self.font_size_var.get()
        scale = 1 if scale_str == "Font size (1)" else int(scale_str)
        for char in text:
            char_code = font_constants.CODE_FROM_CHAR.get(char, '')
            if char_code:
                left_corner = self.draw_letter(char_code, left_corner, scale)

    def draw_letters(self):
        # for line in font_constants.HERSHEY_DATA.split('\n'):
        #     self.draw_letter(line[6:])
        #     input(line)
        while char:= input('Enter letter to draw:\n'):
            self.canvas.delete('all')
            self.draw_letter(font_constants.CODE_FROM_CHAR.get(char, ''))

    def draw_letter(self,
                    line,
                    left_corner=None,
                    scale=10):
        left_corner = left_corner or (self.canvas_width//2, self.canvas_height//2)
        # First 2 chars are num coord pairs
        left_pos = scale * (ord(line[2]) - 82)  # 82 is ord("R")
        right_pos = scale * (ord(line[3]) - 82)
        origin = (left_corner[0] - left_pos, left_corner[1])
        right_corner = (origin[0] + right_pos, origin[1])
        if not self.is_within_canvas(*right_corner):
            return right_corner
        prev_x = prev_y = None
        for x_char, y_char in zip(line[4:-1:2], line[5::2]):
            if x_char == " " and y_char == "R":
                self.text_positions.append(PEN_UP)
                prev_x = prev_y = None
                continue
            x = origin[0] + (ord(x_char) - 82) * scale
            y = origin[1] + (ord(y_char) - 82) * scale
            # TODO: Find max and min y and don't start drawing if they hit the edge
            if not self.is_within_canvas(x, y):
                self.text_positions.append(PEN_UP)
                return right_corner
            self.text_positions.append((x, y))
            if prev_x is not None and prev_y is not None:
                segment = self.canvas.create_line(prev_x, prev_y, x, y,
                                        width=2, fill='black',
                                        capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36)
                self.text_segments.append(segment)
            prev_x = x
            prev_y = y
        self.text_positions.append(PEN_UP)
        return right_corner

    def toggle_sync_mode(self):
        if self.sync_mode:
            self.stop_sync_flag = True
            self.sync_mode = False
        else:
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

    def on_click(self, event):
        if self.is_within_canvas(event.x, event.y):
            self.old_x = event.x
            self.old_y = event.y
            self.positions.append((event.x, event.y))

    def draw(self, event):
        def draw_line():
            return self.canvas.create_line(self.old_x, self.old_y, event.x, event.y,
                                    width=self.line_width, fill=self.color,
                                    capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36)
        if self.old_x == event.x and self.old_y == event.y:
            return  # splprep doesn't like repeating points
        if not self.is_within_canvas(event.x, event.y):
            if not self.straight_line_var.get():
                self.reset(event)
            return
        if self.old_x and self.old_y and self.is_within_canvas(event.x, event.y):
            if self.straight_line_var.get():
                if self.straight_segment is None:
                    self.straight_segment = draw_line()
                self.canvas.coords(self.straight_segment, self.old_x, self.old_y, event.x, event.y)
                return
            self.positions.append((event.x, event.y))
            draw_line()

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
        if not self.is_within_canvas(event.x, event.y):
            # If we've run off the canvas, remove the last position for safety
            try:
                self.positions.pop()
            except IndexError:
                pass
            # If it's a straight segment we won't draw it,
            # so delete the preview
            if self.straight_segment:
                self.canvas.delete(self.straight_segment)
        # If the line has a starting point and this isn't a duplicate point,
        # add the final point. Important for straight segments.
        if (self.old_x is not None and self.old_y is not None and
            not (self.old_x == event.x and self.old_y == event.y)):
            self.positions.append((event.x, event.y))
        self.old_x = None
        self.old_y = None
        self.straight_segment = None
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
            # TODO: Use self.update_position
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

    def update_position(self):
        stationary_count = 0
        tol = 1
        r = 10
        prev_x = None
        prev_y = None
        prev_x_for_exit = 0
        prev_y_for_exit = 0
        x = y = z = -1
        marker_marker = self.canvas.create_oval(
                x-r, self.canvas_height - (y-r),
                x+r, self.canvas_height - (y+r), fill='purple')
        while self.sync_mode or stationary_count < 50:
            position = self.gcode_sender.get_position()
            if position is not None:
                x, y, z = position
                x /= self.x_scale
                y = self.canvas_height - y / self.y_scale
            self.canvas.moveto(marker_marker, x - r, y - r)
            if abs(x - prev_x_for_exit) < tol and abs(y - prev_y_for_exit) < tol:
                stationary_count += 1
            else:
                stationary_count = 0
            prev_x_for_exit = x
            prev_y_for_exit = y
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
            time.sleep(0.025)
        self.canvas.delete(marker_marker)

    def send_text_and_drawings(self):
        self.anchor_text()
        self._update_position_thread = threading.Thread(
            target=self.update_position,
            args=(),
            daemon=True,
        )
        self._update_position_thread.start()
        self.generate_gcode(is_text=True)
        self.generate_gcode(is_text=False)

    def generate_gcode(self, is_text=False):
        if is_text:
            positions = self.text_positions_anchored 
            self.text_positions_anchored = []
        else:
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
            if is_text:
                spline = positions[:pen_up_idx]
            else:
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
            # if line:
            #     print('received', line)
            # if "?" in line:
            #     self.serial_instance.send("DENIED")
            #     continue
            if "G0 Z-5" in line:
                if last_x is not None and last_y is not None:
                    self.preview_canvas.create_oval(last_x-r, last_y-r, last_x+r, last_y+r, fill='red')
                pen_down = False
                continue
            if "G0 Z5" in line:
                if last_x is not None and last_y is not None:
                    self.preview_canvas.create_oval(last_x-r, last_y-r, last_x+r, last_y+r, fill='purple')
                pen_down = True
                continue
            if "G1" in line:
                try:
                    xScaled = float(line[line.index("X")+1:].split(" ")[0])
                    yScaled = float(line[line.index("Y")+1:].split(" ")[0])
                except Exception as e:
                    print(e)
                    print('line', line)
                    continue
                x = xScaled * 2  # TODO: make this x_scale
                y = 405*2 - yScaled * 2  # TODO : configurable
                if pen_down:
                    self.preview_canvas.create_line(last_x, last_y, x, y, width=self.line_width, fill=self.color)

                last_x, last_y = x, y




def main(argv):
    del argv  # unused
    root = customtkinter.CTk()
    if SERIAL_PORT.value and SERIAL_PORT.value.lower() != 'none':
        gcode_sender = GCodeSender(SERIAL_PORT.value)
    else:
        gcode_sender = GCodeSender(serial_port='loop://', allow_position_query=False)
        preview_app = PreviewApp(root, gcode_sender.serial_instance)
    app = DrawingApp(root, gcode_sender)
    root.mainloop()

if __name__ == '__main__':
    app.run(main)
