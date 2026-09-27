# Facial Recognition Access Control and Surveillance System (FRACS) Description

## Overview
FRACS is a comprehensive system designed for real-time access control and surveillance. It leverages facial recognition technology to grant or deny access to secured areas based on recognized faces. The system also includes features for live streaming, user management, and remote control capabilities.

## Features
1. **Facial Recognition:** Utilizes machine learning algorithms to identify faces and grant access based on pre-defined permissions.
2. **Real-Time Access Control:** Controls physical access to secured areas by interfacing with a servo motor to lock or unlock gates or doors.
3. **Web Portal:** Provides a user-friendly interface for managing access permissions, viewing live streams, and monitoring system activity.
4. **Live Streaming:** Allows users to view real-time video streams of monitored areas for surveillance purposes.
5. **Remote Control:** Enables remote locking and unlocking of access points through the web portal, providing flexibility and convenience to users.

## Architecture
The system comprises:
- **Face Recognition Model:** Implements facial recognition algorithms for identifying individuals.
- **Raspberry Pi:** Acts as the central processing unit, controlling the servo motor and interfacing with the face recognition model.
- **ESP32:** Attached to the servo motor for physical control of access points.
- **FastAPI Web Portal:** Hosted on the Raspberry Pi, it provides a web-based interface for users to interact with the system, with a SQLite database for enrolled people, their photos and an access log.
- **Camera:** Captures live video streams for facial recognition and surveillance purposes.

## Technologies
- Machine Learning: Used for facial recognition.
- Raspberry Pi: Controls hardware components and hosts the web portal.
- ESP32: Interfaces with the servo motor for physical access control.
- FastAPI + Socket.IO: Web framework and live updates for the user interface.
- SQLite (via SQLAlchemy): Stores enrolled people, face encodings and access events.
- OpenCV: Library for computer vision tasks, including face detection and recognition.
- HTML/CSS/JavaScript: Front-end technologies for the web portal.

## User Interface
The user interface features intuitive navigation, allowing users to easily manage access permissions, view live streams, and control access points. It includes interactive elements for unlocking or locking gates and displaying system status.

## Functionality
- **Facial Recognition:** The system continuously analyzes live video feeds, identifying faces and matching them against a database of authorized individuals.
- **Access Control:** Upon recognition, the system triggers the servo motor to either unlock or lock access points based on predefined permissions.
- **Web Portal:** Users can log in to the web portal to view live streams, manage access permissions, and remotely control access points.
- **Surveillance:** The system provides real-time video feeds for monitoring and surveillance purposes, enhancing security measures.

## Security
- **Authentication:** Users are required to authenticate themselves before accessing the web portal.
- **Authorization:** Access permissions are enforced based on user roles and privileges.
- **Encryption:** Data transmission between components is encrypted to prevent unauthorized access.
- **Data Protection:** Facial recognition data and user information are securely stored and protected from unauthorized access or tampering.

## Performance
- **Response Times:** The system maintains low latency for real-time facial recognition and access control.
- **Throughput:** Handles multiple simultaneous requests efficiently, ensuring smooth operation.
- **Scalability:** Designed to scale with the addition of more cameras or access points.
- **Resource Utilization:** Optimizes resource usage to ensure efficient operation on Raspberry Pi hardware.

## Integration
The system can integrate with external databases for user management, APIs for additional functionality, and external services for enhanced surveillance capabilities.

## Maintenance and Support
Regular maintenance procedures include software updates, database backups, and system health checks. Troubleshooting guides and user manuals are provided for ongoing support.

## Requirements
System requirements include hardware components (Raspberry Pi, ESP32, camera), software dependencies (FastAPI, OpenCV, face_recognition), and network connectivity for remote access.

## Use Cases
1. **Office Access Control:** Employees use facial recognition to gain access to secure areas within the office premises.
2. **Home Security:** Homeowners remotely monitor their property and control access to entry points using the web portal.
3. **Retail Store Surveillance:** Store managers monitor customer activity and manage access to restricted areas in real-time.
4. **Educational Institutions:** Schools or universities use the system to control access to classrooms, laboratories, or administrative offices based on user permissions.
5. **Health Institutions:** Hospitals or laboratories use the system to control access to medication and wards.





## Setup

On the Raspberry Pi:

```bash
pip install -r requirements.txt          # dlib must be installable; on a Pi use piwheels or your distro's package
export FRACS_ESP32_URL=http://<esp32-ip>  # the lock controller running wifi_servo/wifi_servo.ino
python supercam.py                       # serves the portal on http://<pi>:8000
```

To move the photos in `dataset/<PersonName>/` into the database and train on them in one step:

```bash
python -m app.cli import-dataset dataset --deny Pemphero --train
```

After that, people are managed from the portal: add a person, capture photos from the camera or upload them, choose whether they are granted access, and press **Train**. Training only encodes new photos, and new faces are recognized as soon as it finishes; no restart is needed.

Settings are environment variables (see `app/config.py`): `FRACS_DATA_DIR` (database and photos, default `./data`), `FRACS_ESP32_URL`, `FRACS_CAMERA_INDEX`, `FRACS_CAMERA_FLIP`, `FRACS_MATCH_TOLERANCE`, `FRACS_RECOGNITION`, `FRACS_CORS_ORIGINS`, `FRACS_HOST`, `FRACS_PORT`.

Tests (these don't need a camera, an ESP32 or dlib): `pip install -r requirements-dev.txt && pytest`.

## Contributing
Contributions are welcome! Please fork the repository, make your changes, and submit a pull request. For major changes, please open an issue first to discuss the proposed changes.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


