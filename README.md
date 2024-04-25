# Face Recognition Access Control System

## Overview
The Face Recognition Access Control System is a real-time system that utilizes machine learning for face recognition, a Raspberry Pi for hardware control, and Flask for the web portal. The system allows owners to manage access to items of value, such as safes or rooms, by controlling a servo motor based on recognized faces. Users can view the live stream and control access permissions through the web portal.

## Features
- Face recognition using machine learning
- Real-time servo motor control based on recognized faces
- Web portal built with Flask for user interaction
- Live stream viewing capability
- Access control management for items of value

## System Architecture
The system consists of the following components:
1. Face Recognition Model: Utilizes machine learning algorithms for face detection and recognition.
2. Raspberry Pi: Controls the servo motor and interfaces with the face recognition model.
3. Flask Web Portal: Provides a user-friendly interface for managing access permissions and viewing the live stream.

## Installation
1. Clone the repository to your Raspberry Pi.
2. Install the necessary dependencies by running `pip install -r requirements.txt`.
3. Train the face recognition model using labeled images of authorized users.
4. Run the Flask application using `python app.py`.
5. Access the web portal from any device connected to the same network as the Raspberry Pi.

## Usage
1. Access the web portal through the provided URL.
2. Register authorized users by uploading their images and providing their names.
3. Configure access permissions for each user.
4. Start the system, and it will begin recognizing faces in real-time.
5. View the live stream and monitor access events through the web portal.
6. Control the servo motor to grant or deny access to items of value.

## Contributing
Contributions are welcome! Please fork the repository, make your changes, and submit a pull request. For major changes, please open an issue first to discuss the proposed changes.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements
- Special thanks to [Insert Name] for their contributions to the face recognition model.
- Thanks to [Insert Name] for their assistance with hardware setup and integration.
