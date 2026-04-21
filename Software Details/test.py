import cv2
cap = cv2.VideoCapture("http://10.91.2.59/stream")
print("Opened:", cap.isOpened())
ret, frame = cap.read()
print("Frame:", ret, frame.shape if ret else "None")
cap.release()