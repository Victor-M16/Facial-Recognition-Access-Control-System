from flask import Flask, render_template, Response
import cv2
import threading
import time
import pickle
import face_recognition
from flask_socketio import SocketIO, emit
import requests
import json
import time

ESP32_IP = "192.168.8.173"  # Replace with the IP address of your ESP32
def get_lock_status():
    url = f"http://{ESP32_IP}:80/lock-status"  # Updated endpoint URL
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        print("Successfully linked ESP32")
        return data["status"]
    else:
        print("Failed to get lock status")
        return None

def lock():
    url = f"http://{ESP32_IP}:80/lock"  # Updated endpoint URL
    response = requests.post(url)
    if response.status_code == 200:
        print("Lock command sent successfully")
    else:
        print("Failed to send lock command")

def unlock():
    url = f"http://{ESP32_IP}:80/unlock"  # Updated endpoint URL
    response = requests.post(url)
    if response.status_code == 200:
        print("Unlock command sent successfully")
    else:
        print("Failed to send unlock command")



app = Flask(__name__)
socketio = SocketIO(app)




# Determine faces from encodings.pickle file model created from train_model.py
encodingsP = "/home/mjima/facial_recognition/supercam/superstream/encodings.pickle"

# Load the known faces and embeddings along with OpenCV's Haar
# cascade for face detection
print("[INFO] loading encodings + face detector...")
data = pickle.loads(open(encodingsP, "rb").read())

# Dictionary to store known faces
known_faces = {}

# Loop through the encodings and extract unique faces
for i, encoding in enumerate(data["encodings"]):
    name = data["names"][i]
    if name not in known_faces.values():
        known_faces[i] = name

known_faces_json = json.dumps(known_faces)


# Default namespace handlers
@socketio.on('connect')
def handle_connect():
    print('Client connected to websocket')

@socketio.on('message')
def handle_message(message):
    print('Received message:', message)
    socketio.emit('message', message)

# '/faces' namespace handlers
@socketio.on('connect', namespace="/faces")
def handle_connect_faces():
    print('Client connected to faces websocket') 
    socketio.emit('message', known_faces_json, namespace='/faces')


@socketio.on('message', namespace='/faces')
def send_message_faces(message):
    print('Sent:', message)
    # Broadcast the message to all clients in the '/faces' namespace
    socketio.emit('message', message, namespace='/faces')


print(known_faces)
print(known_faces_json)




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
    currentname = "Unknown "
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
                    name = data["names"][i] #change name to the matched one
                    counts[name] = counts.get(name, 0) + 1
                name = max(counts, key=counts.get)
                if currentname != name:
                    currentname = name
                    print(currentname)
                    handle_message(currentname)
                    if currentname in known_faces.values():
                        unlock()
                    
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
    lock()
    get_lock_status()
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



