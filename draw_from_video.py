"""Connects to webcam and tracks the most red part of the image as if it were drawing.

Works pretty well against a white background, using a pen with a red rubber band 
scrunched around the bottom. Outputs the trajectory to a tkinter canvas.
"""

import tkinter as tk
import Main
import cv2
from absl import app
from absl import flags
import numpy as np
import dataclasses

CAMERA_INDEX = flags.DEFINE_integer("camera_index", None, "Which camera to stream from.")
BLUR_RADIUS = flags.DEFINE_integer(
    "blur_radius", 41, "How much to blur image before finding reddest region. Odd.")

BLUE = (255, 0, 0)

@dataclasses.dataclass
class CanvasPoint:
    x: float
    y: float


def reddest_pixel(image):
    """Coordinates of the brightest single pixel in the image."""
    image = image[:, :, 2].astype(np.int32) * 2 - image[:, :, 0] - image[:, :, 1]
    image = np.clip(image, 0, 255).astype(np.uint8)
    image = cv2.GaussianBlur(image, (BLUR_RADIUS.value, BLUR_RADIUS.value), 0)
    (min_val, max_val, min_coords, max_coords) = cv2.minMaxLoc(image)
    return max_coords, cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


def main(argv):
    video_capture = cv2.VideoCapture(CAMERA_INDEX.value)
    if video_capture.isOpened(): # try to get the first frame
        rval, frame = video_capture.read()
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    else:
        rval = False
    root = tk.Tk()
    cv2.namedWindow("preview")
    app = Main.DrawingApp(root)
    while rval:
        pixel, frame = reddest_pixel(frame)
        cv2.circle(img=frame, center=pixel, radius=BLUR_RADIUS.value, color=BLUE, thickness=2)
        pixel_in_frame = np.asarray(pixel) / np.asarray(frame.shape[:2]) * np.array((200*5, 280*5))
        canvas_point = CanvasPoint(*pixel_in_frame)
        app.draw(canvas_point)
        cv2.imshow("preview", frame)
        key = cv2.waitKey(20)
        root.update_idletasks()
        root.update()
        rval, frame = video_capture.read()
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    video_capture.release()
    cv2.destroyWindow("preview")

if __name__ == "__main__":
    app.run(main)
