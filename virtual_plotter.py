"""Listens for G-code on a serial port and draws what the plotter would draw."""

import tkinter as tk
import threading

class VirtualPlotter:
    def __init__(self, root, serial_instance, plotter_width, plotter_height, canvas_scale):
        self.root = root
        self.serial_instance = serial_instance
        self.line_width = 2
        self.color = 'black'
        self.scale = canvas_scale
        self.height = plotter_height
        preview_window = tk.Toplevel(self.root)
        preview_window.title("Virtual Plotter")
        
        preview_canvas = tk.Canvas(
            preview_window, bg='white', 
            width=plotter_width * canvas_scale, height=plotter_height * canvas_scale)
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
                x = xScaled * self.scale
                y = (self.height - yScaled) * self.scale
                if pen_down:
                    self.preview_canvas.create_line(last_x, last_y, x, y, width=self.line_width, fill=self.color)

                last_x, last_y = x, y

