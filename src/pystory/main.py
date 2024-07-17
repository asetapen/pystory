import cv2
import pyautogui
import time
from datetime import datetime

LOG_DIR = "/home/adam/.pc-history"
CADENCE_SECONDS = 3


def take_screenshot(current_time: str) -> None:
    screenshot = pyautogui.screenshot()
    screenshot.save(f"{LOG_DIR}/screenshot_{current_time}.png")


def take_webcam_picture(current_time: str) -> None:
    cam = cv2.VideoCapture(0)
    ret, frame = cam.read()
    if ret:
        cv2.imwrite(f"{LOG_DIR}/webcam_{current_time}.png", frame)
    cam.release()


def main():
    while True:
        time_now = datetime.now().strftime('%Y%m%d_%H%M%S')
        take_screenshot(time_now)
        take_webcam_picture(time_now)
        time.sleep(CADENCE_SECONDS)


if __name__ == "__main__":
    main()
