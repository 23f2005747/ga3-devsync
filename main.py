import cv2

cap = cv2.VideoCapture("attendee_checkin.webm")

ret, frame = cap.read()

if ret:
    cv2.imwrite("frame_test.jpg", frame)
    print("Frame saved as frame_test.jpg")
else:
    print("Could not read frame")

cap.release()