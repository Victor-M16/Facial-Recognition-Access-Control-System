#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

const char* ssid = "*****"; // replace with the ssid and password of the network the RPI4 is connected to
const char* password = "*****";

const int serverPort = 80; //the port on which the server is running to receive requests from the raspberry pi
const int servoPin = 13; // put the gpio pin number the servo is attached to

const int LOCK_ANGLE = 180;
const int UNLOCK_ANGLE = 70;

Servo servo;
int lockStatus = 0; // Initial lock status (0 for unlocked, 1 for locked)

AsyncWebServer server(serverPort);

void setup() {
  Serial.begin(115200);
  
  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("Connected to WiFi");

  // Initialize servo
  servo.setPeriodHertz(50);  // Standard 50 Hz servo
  servo.attach(servoPin, 1000, 2000); // min/max pulse width

  // Route setup
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(200, "text/plain", "Hello from ESP32!");
  });

  server.on("/lock-status", HTTP_GET, [](AsyncWebServerRequest *request){ //this is therequest handler that returns whether the gate is locked
    DynamicJsonDocument doc(100);
    doc["status"] = lockStatus;
    String jsonStr;
    serializeJson(doc, jsonStr);
    request->send(200, "application/json", jsonStr);
  });

  server.on("/lock", HTTP_POST, [](AsyncWebServerRequest *request){ //this handler locks the gate
    lockStatus = 1;
    Serial.println("Lock command received. Locking door...");
    servo.write(LOCK_ANGLE);
    request->send(200);
    Serial.println("Locked successfully.");
  });

  server.on("/unlock", HTTP_POST, [](AsyncWebServerRequest *request){ // this handler unlocks the gate
    lockStatus = 0;
    Serial.println("Unlock command received. Unlocking door...");
    servo.write(UNLOCK_ANGLE);
    request->send(200);
    Serial.println("Access granted.");
  });

  server.begin();
}

void loop() {
  // Nothing to do in loop since AsyncWebServer runs asynchronously
}
