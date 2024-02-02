import tkinter as tk
from collections import deque
import math

class DrawingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Drawing App")

        # Plotter Dimensions in mm
        self.plotter_width = 280
        self.plotter_height = 200

        # Canvas Size in Pixels
        self.canvas_width = self.plotter_width * 5
        self.canvas_height = self.plotter_height * 5

        self.canvas = tk.Canvas(root, bg='white', width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(padx=10, pady=10)

        self.setup()
        self.canvas.bind("<B1-Motion>", self.draw)
        self.canvas.bind("<ButtonRelease-1>", self.reset)

        # Button to generate G-code
        self.generate_button = tk.Button(root, text="Generate G-code", command=self.generate_gcode)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 20), pady=10)

        # Button to preview drawing
        self.preview_button = tk.Button(root, text="Preview Drawing", command=self.preview_drawing)
        self.preview_button.pack(side=tk.LEFT, pady=10)

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

    def draw(self, event):
        if self.old_x and self.old_y and self.is_within_canvas(event.x, event.y):
            # Draw line
            self.canvas.create_line(self.old_x, self.old_y, event.x, event.y,
                                   width=self.line_width, fill=self.color,
                                   capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36)

            # Store position
            self.positions.append((event.x, event.y))
            print(f"Stored Position: {event.x}, {event.y}")

        self.old_x = event.x
        self.old_y = event.y

    def reset(self, event):
        self.old_x = None
        self.old_y = None
        
    def preview_drawing(self):
        preview_window = tk.Toplevel(self.root)
        preview_window.title("Drawing Preview")
        
        preview_canvas = tk.Canvas(preview_window, bg='white', width=self.canvas_width, height=self.canvas_height)
        preview_canvas.pack()

        last_x, last_y = None, None
        deadzone = 10
        positions_copy = self.positions.copy()  # Use a copy to preserve original positions

        while positions_copy:
            x, y = positions_copy.popleft()

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

    def generate_gcode(self, filename='output.txt', deadzone=20):
        with open(filename, 'w') as file:
            last_x, last_y = None, None
            pen_up = True

            while self.positions:
                x, y = self.positions.popleft()

                if last_x is not None and last_y is not None:
                    # Calculate distance to previous point
                    distance = math.sqrt((x - last_x) ** 2 + (y - last_y) ** 2)

                    if distance > deadzone and not pen_up:
                        # Pen up command
                        file.write("M0 ;Pen up\n")
                        pen_up = True
                
                xScaled = self.x_scale * x
                yScaled = self.y_scale * y

                if pen_up:
                    # Move to new position with pen up
                    file.write(f"G0 X{xScaled} Y{yScaled}\n")
                    # Pen down command
                    file.write("M1 ;Pen down\n")
                    pen_up = False
                else:
                    # Move to new position with pen down
                    file.write(f"G1 X{xScaled} Y{yScaled}\n")

                last_x, last_y = x, y

            # Ensure pen is up at the end
            file.write("M5 ;Pen up\n")

        print(f"G-code written to {filename}")

def main():
    root = tk.Tk()
    app = DrawingApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
