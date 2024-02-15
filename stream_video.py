"""Shows a camera video stream with one of the brightest pixels circled in blue.

Usage:
python stream_video.py --camera_index=4

If you don't know the camera index, run `python stream_video.py` and it will
print the available cameras. --camera_index=0 will probably be a built-in webcam.
"""
import cv2
from absl import app
from absl import flags

CAMERA_INDEX = flags.DEFINE_integer("camera_index", None, "Which camera to stream from.")

BLUE = (255, 0, 0)


def get_camera_indices():
    # checks the first 10 indices.
    available_cameras = []
    for i in range(10):
        video_capture = cv2.VideoCapture(i)
        if video_capture.read()[0]:
            available_cameras.append(i)
            video_capture.release()
    return available_cameras


def brightest_pixel(image):
    """Coordinates of the brightest single pixel in the image."""
    gray_img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    (min_val, max_val, min_coords, max_coords) = cv2.minMaxLoc(gray_img)
    return max_coords


def main(argv):
    del argv
    if CAMERA_INDEX.value is None:
        print("No value passed for --camera_index; checking for connected cameras.",
              "Some errors are expected.\n")
        available_cameras = get_camera_indices()
        print("\nRerun the binary with one of these available cameras:", available_cameras)
        return
    cv2.namedWindow("preview")
    video_capture = cv2.VideoCapture(CAMERA_INDEX.value)

    if video_capture.isOpened(): # try to get the first frame
        rval, frame = video_capture.read()
    else:
        rval = False

    print("Press Esc to exit (with image window selected).")
    while rval:
        bright_coords = brightest_pixel(frame)
        cv2.circle(img=frame, center=bright_coords, radius=5, color=BLUE, thickness=2)
        cv2.imshow("preview", frame)
        rval, frame = video_capture.read()
        key = cv2.waitKey(20)
        if key == 27: # exit on ESC
            break

    video_capture.release()
    cv2.destroyWindow("preview")

if __name__ == "__main__":
    app.run(main)