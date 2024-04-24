from flask import Flask, render_template, Response
import cv2
import threading
import time
import pickle
import face_recognition
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)


@socketio.on('message')
def handle_message(message):
    print('Received message:', message)
    socketio.emit('message', message)

# Handle WebRTC signaling messages
@socketio.on('offer')
def handle_offer(offer):
    emit('answer', offer, broadcast=True)

@socketio.on('candidate')
def handle_candidate(candidate):
    emit('candidate', candidate, broadcast=True)


# Determine faces from encodings.pickle file model created from train_model.py
encodingsP = "/home/mjima/facial_recognition/supercam/superstream/encodings.pickle"
known_faces = {1:"Victor",
               2:"Pemphero",
               3:"Roberta",
               4:"Cliff"}


# Load the known faces and embeddings along with OpenCV's Haar
# cascade for face detection
print("[INFO] loading encodings + face detector...")
data = pickle.loads(open(encodingsP, "rb").read())

# Singleton pattern to ensure only one camera instance
class VideoCameraSingleton:
    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = VideoCamera()
        return cls._instance

class VideoCamera:
    def __init__(self):
        self.video_capture = cv2.VideoCapture(0)  # Use the first camera (index 0)

        # Set camera resolution
        self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # Initialize lock for thread-safe access to camera frames
        self.lock = threading.Lock()

    def __del__(self):
        self.video_capture.release()

    def get_frame(self):
        with self.lock:
            success, frame = self.video_capture.read()
            if not success:
                return None
            # Flip the frame vertically
            frame = cv2.flip(frame, 0)
            return frame

def recognize_faces(camera):
    
    print("face recon function working")
    currentname = "unknown"
    while True:
        frame = camera.get_frame()
        if frame is None:
            break
        boxes = face_recognition.face_locations(frame)
        encodings = face_recognition.face_encodings(frame, boxes)
        names = []
        for encoding in encodings:
            matches = face_recognition.compare_faces(data["encodings"], encoding)
            name = "Unknown"
            if True in matches:
                matchedIdxs = [i for (i, b) in enumerate(matches) if b]
                counts = {}
                for i in matchedIdxs:
                    name = data["names"][i]
                    counts[name] = counts.get(name, 0) + 1
                name = max(counts, key=counts.get)
                if currentname != name:
                    currentname = name
                    # Need a way to interact with the WebSocket here so that the client receives the newly detected current_name only when it is different from the one detected before
                    print(currentname)
                    handle_message(currentname)
            names.append(name)

def gen(camera):
    print("gen function working")
    while True:
        frame = camera.get_frame()
        if frame is None:
            break
        ret, jpeg = cv2.imencode('.jpg', frame)
        if not ret:
            break
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.01)  # Adjust the delay as needed. I like the way it was showing with 0.01 more than 0.1 

@app.route('/')
def index():
    return render_template('index2.html')

def video_feed():
    camera = VideoCameraSingleton.get_instance()
    face_thread = threading.Thread(target=recognize_faces, args=(camera,))
    face_thread.daemon = True
    face_thread.start()
    print("video_feed function working")
    return Response(gen(camera), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed')
def video_feed_route():
    return video_feed()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000)




# import cv2
# import numpy as np
# from flask import Flask, render_template, Response
# from flask_socketio import SocketIO, emit
# import base64
# import threading
# import time
# import pickle
# import face_recognition

# app = Flask(__name__)
# socketio = SocketIO(app)

# # Load the known faces and embeddings
# encodingsP = "encodings.pickle"
# data = pickle.loads(open(encodingsP, "rb").read())

# # Video streaming function with face recognition
# def gen():
#     # Open the camera
#     cap = cv2.VideoCapture(0)

#     while True:
#         # Capture frame-by-frame
#         ret, frame = cap.read()

#         # Perform face recognition
#         boxes = face_recognition.face_locations(frame)
#         encodings = face_recognition.face_encodings(frame, boxes)

#         # Loop through the detected faces
#         for encoding in encodings:
#             matches = face_recognition.compare_faces(data["encodings"], encoding)
#             name = "Unknown"

#             # Check if a match is found
#             if True in matches:
#                 matchedIdxs = [i for (i, b) in enumerate(matches) if b]
#                 counts = {}

#                 # Determine the recognized face with the most votes
#                 for i in matchedIdxs:
#                     name = data["names"][i]
#                     counts[name] = counts.get(name, 0) + 1
#                 name = max(counts, key=counts.get)

#                 # Draw a rectangle and label around the face
#                 y1, x2, y2, x1 = boxes[0]
#                 cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
#                 cv2.putText(frame, name, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

#         # Convert frame to base64 string
#         ret, buffer = cv2.imencode('.jpg', frame)
#         frame_base64 = base64.b64encode(buffer)

#         # Send the frame to the client
#         socketio.emit('video_stream', {'image': frame_base64.decode('utf-8')})

#         # Break the loop if 'q' is pressed
#         if cv2.waitKey(1) & 0xFF == ord('q'):
#             break

#     # Release the camera
#     cap.release()

# @app.route('/')
# def index():
#     return render_template('index2.html')

# @socketio.on('connect')
# def connect():
#     print('Client connected')
#     emit('connected', {'data': 'Connected'})

# if __name__ == '__main__':
#     threading.Thread(target=gen).start()
#     socketio.run(app, host='0.0.0.0', port=8000)
