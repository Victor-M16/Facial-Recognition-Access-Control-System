from flask import Flask, render_template, Response, jsonify
import cv2
import threading
import time
import pickle
import face_recognition
from flask_socketio import SocketIO, emit
import requests
import json
import time
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import LargeBinary
from flask import request
import os
from flask import send_from_directory
import base64
from flask_cors import CORS
from imutils import paths


app = Flask(__name__)
socketio = SocketIO(app)



CORS(app, resources={r"/api/lock": {"origins": "http://raspberrypi16.local:8000"},
                     r"/api/unlock": {"origins": "http://raspberrypi16.local:8000"}})



# Global flag to control face recognition
face_recognition_enabled = True


# Directory where captured images will be stored
UPLOAD_FOLDER = '/home/mjima/flask/captured_images'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


ESP32_IP = "192.***.**.***"  # Replace with the IP address of your ESP32
def get_lock_status():
    url = f"http://{ESP32_IP}:80/lock-status"  # Updated endpoint URL
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            print("Successfully linked ESP32")
            return data["status"]
        else:
            print("Failed to get lock status")
            return None
    except:
        pass

def lock():
    try:
        url = f"http://{ESP32_IP}:80/lock"  # Updated endpoint URL
        response = requests.post(url)
        if response.status_code == 200:
            print("Lock command sent successfully")
        else:
            print("Failed to send lock command")
    except:
        pass

@app.route('/api/lock', methods=['POST'])
def lock_route():
    try:
        url = f"http://{ESP32_IP}:80/lock"  # Updated endpoint URL
        response = requests.post(url)
        if response.status_code == 200:
            print("Lock command sent successfully")
            return jsonify({"message": "Lock command sent successfully"}), 200
        else:
            print("Failed to send lock command")
            return jsonify({"message": "Failed to send lock command"}), 500
    except Exception as e:
        print("Error:", e)
 

def unlock():
    try:
        url = f"http://{ESP32_IP}:80/unlock"  # Updated endpoint URL
        response = requests.post(url)
        if response.status_code == 200:
            print("Unlock command sent successfully")
        else:
            print("Failed to send unlock command")
    except:
        pass

@app.route('/api/unlock', methods=['POST'])
def unlock_route():
    try:
        url = f"http://{ESP32_IP}:80/unlock"  # Updated endpoint URL
        response = requests.post(url)
        if response.status_code == 200:
            print("Unlock command sent successfully")
            return jsonify({"message": "Unlock command sent successfully"}), 200
        else:
            print("Failed to send unlock command")
            return jsonify({"message": "Failed to send unlock command"}), 500
    except Exception as e:
        print("Error:", e)
 



# Determine faces from encodings.pickle file model created from train_model.py
encodingsP = "/home/mjima/flask/encodings.pickle"

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
# print(known_faces_json)




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
    global face_recognition_enabled

    

    currentname = "Unknown "
    while True:
        if face_recognition_enabled:
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

                        if currentname in ["Pemphero", "Unknown"]:
                                lock()

                        if currentname in known_faces.values():
                            if currentname != "Pemphero":                            
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
    return render_template('index0.html')

@app.route('/train_model')
def train_model_route():
    train_thread = threading.Thread(target=train_model)
    train_thread.start()
    return render_template('training.html')



@app.route('/capture_image', methods=['POST'])
def capture_image():
    image_data = request.json.get('imageData')
    # Generate a unique filename for the captured image
    filename = os.path.join(UPLOAD_FOLDER, 'captured_image.jpg')
    # Save the captured image data to a file
    with open(filename, 'wb') as f:
        f.write(base64.b64decode(image_data.split(',')[1]))
    print("Image captured")
    # Return a response indicating success
    return 'Image captured successfully!', 200

@app.route('/view_captured_image')
def view_captured_image():
    # Get the path to the captured image file
    filename = os.path.join(UPLOAD_FOLDER, 'captured_image.jpg')
    # Check if the file exists
    if os.path.exists(filename):
        # Serve the captured image file
        return send_from_directory(UPLOAD_FOLDER, 'captured_image.jpg')
    else:
        # Return a 404 error if the file does not exist
        return 'Captured image not found', 404
    

# Route for recording a video
@app.route('/record_video')
def record_video():
    # Implement functionality to record a video and store it in a database
    # This might involve accessing the camera, recording the video, and saving it to a database
    return render_template('record_video.html')

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


def train_model():
    global face_recognition_enabled 
    face_recognition_enabled = False

    while True:
        if not face_recognition_enabled:
            print("Stopping Face Recognition model...")
            # our images are located in the dataset folder
            print("[INFO] start processing faces...")
            imagePaths = list(paths.list_images("dataset"))

            # initialize the list of known encodings and known names
            knownEncodings = []
            knownNames = []

            # loop over the image paths
            for (i, imagePath) in enumerate(imagePaths):
                if not face_recognition_enabled:
                    # extract the person name from the image path
                    print("[INFO] processing image {}/{}".format(i + 1,
                        len(imagePaths)))
                    message = "[INFO] processing image {}/{}".format(i + 1, len(imagePaths))

                    handle_message(message)
                    name = imagePath.split(os.path.sep)[-2]

                    # load the input image and convert it from RGB (OpenCV ordering)
                    # to dlib ordering (RGB)
                    image = cv2.imread(imagePath)
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

                    # detect the (x, y)-coordinates of the bounding boxes
                    # corresponding to each face in the input image
                    boxes = face_recognition.face_locations(rgb,
                        model="hog")

                    # compute the facial embedding for the face
                    encodings = face_recognition.face_encodings(rgb, boxes)

                    # loop over the encodings
                    for encoding in encodings:
                        # add each encoding + name to our set of known names and
                        # encodings
                        knownEncodings.append(encoding)
                        knownNames.append(name)

            # dump the facial encodings + names to disk
            print("[INFO] serializing encodings...")
            data = {"encodings": knownEncodings, "names": knownNames}
            f = open("encodings.pickle", "wb")
            f.write(pickle.dumps(data))
            f.close()
            print("Model training complete")
            handle_message("Model training complete")
            face_recognition_enabled = True


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000)


