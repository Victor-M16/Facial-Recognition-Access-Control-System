#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <ESP32Servo.h>
#include "esp_random.h"
#include "mbedtls/md.h"

#include "fracs_auth.h"

const char* ssid = "*****"; // replace with the ssid and password of the network the RPI4 is connected to
const char* password = "*****";

// Shared secret with the Pi (FRACS_ESP32_SECRET). Use the same long random value on both,
// e.g. from: python -c "import secrets; print(secrets.token_hex(32))"
// Every command is refused until this is changed from the placeholder.
const char* LOCK_SECRET = "*****";

const int serverPort = 80; //the port on which the server is running to receive requests from the raspberry pi
const int servoPin = 13; // put the gpio pin number the servo is attached to

const int LOCK_ANGLE = 180;
const int UNLOCK_ANGLE = 70;

// Failure behaviour (see README "When power or the network fails"):
// - On power-up the servo is driven to LOCK before anything else, so a reboot never leaves the door open.
// - Every unlock is temporary. The ESP32 relocks by itself after UNLOCK_MS, whether or not the Pi
//   or the Wi-Fi is still there, so losing the network can't strand the door unlocked.
const unsigned long UNLOCK_MS = 5000;
const unsigned long WIFI_RETRY_MS = 30000;

Servo servo;
SemaphoreHandle_t stateMutex;
int lockStatus = 1;              // 1 = locked, 0 = unlocked
unsigned long unlockedAt = 0;
fracs::NonceStore nonces;

AsyncWebServer server(serverPort);

void fracs_hmac_sha256(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len, uint8_t out[32]) {
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, key_len, msg, msg_len, out);
}

void fracs_random_bytes(uint8_t* out, size_t len) {
  // Hardware RNG; truly random while the radio is on
  esp_fill_random(out, len);
}

// Web handlers run on the network task and the relock timer on the main loop, so all
// state changes go through here under the mutex
void setLocked(bool locked, const char* reason) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  servo.write(locked ? LOCK_ANGLE : UNLOCK_ANGLE);
  lockStatus = locked ? 1 : 0;
  unlockedAt = locked ? 0 : millis();
  xSemaphoreGive(stateMutex);
  Serial.printf("%s (%s)\n", locked ? "Locked" : "Unlocked", reason);
}

const char* headerValue(AsyncWebServerRequest* request, const char* name) {
  if (!request->hasHeader(name)) return nullptr;
  return request->getHeader(name)->value().c_str();
}

// Sends the error response itself and returns false if the request isn't properly signed
bool authorized(AsyncWebServerRequest* request, const char* action) {
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  fracs::Result result = fracs::verify(nonces, LOCK_SECRET, action,
                                       headerValue(request, "X-Fracs-Nonce"),
                                       headerValue(request, "X-Fracs-Signature"), millis());
  xSemaphoreGive(stateMutex);
  switch (result) {
    case fracs::OK:
      return true;
    case fracs::NOT_CONFIGURED:
      Serial.println("Refusing command: LOCK_SECRET is not set");
      request->send(503, "text/plain", "LOCK_SECRET not configured");
      return false;
    default:
      Serial.printf("Rejected unauthenticated %s request (reason %d)\n", action, result);
      request->send(401, "text/plain", "Unauthorized");
      return false;
  }
}

void setup() {
  Serial.begin(115200);

  // Lock first, before waiting on anything else
  stateMutex = xSemaphoreCreateMutex();
  fracs::init(nonces);
  servo.setPeriodHertz(50);  // Standard 50 Hz servo
  servo.attach(servoPin, 1000, 2000); // min/max pulse width
  setLocked(true, "power-up");

  if (!fracs::secret_configured(LOCK_SECRET)) {
    Serial.println("WARNING: LOCK_SECRET is not set; all lock commands will be refused");
  }

  // Connect without blocking: the relock timer in loop() must keep running even if Wi-Fi never comes up
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, password);

  // Route setup
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(200, "text/plain", "Hello from ESP32!");
  });

  server.on("/nonce", HTTP_GET, [](AsyncWebServerRequest *request){ // step 1 of every command, see fracs_auth.h
    char nonce[fracs::NONCE_HEX_LEN + 1];
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    fracs::issue_nonce(nonces, millis(), nonce);
    xSemaphoreGive(stateMutex);
    request->send(200, "application/json", String("{\"nonce\":\"") + nonce + "\"}");
  });

  server.on("/lock-status", HTTP_GET, [](AsyncWebServerRequest *request){ //this is therequest handler that returns whether the gate is locked
    if (!authorized(request, "status")) return;
    request->send(200, "application/json", String("{\"status\":") + lockStatus + "}");
  });

  server.on("/lock", HTTP_POST, [](AsyncWebServerRequest *request){ //this handler locks the gate
    if (!authorized(request, "lock")) return;
    setLocked(true, "command");
    request->send(200);
  });

  server.on("/unlock", HTTP_POST, [](AsyncWebServerRequest *request){ // this handler unlocks the gate for UNLOCK_MS
    if (!authorized(request, "unlock")) return;
    setLocked(false, "command");
    request->send(200);
  });

  server.begin();
}

void loop() {
  static unsigned long lastWifiAttempt = 0;
  static bool wasConnected = false;

  xSemaphoreTake(stateMutex, portMAX_DELAY);
  bool relockDue = lockStatus == 0 && millis() - unlockedAt >= UNLOCK_MS;
  xSemaphoreGive(stateMutex);
  if (relockDue) {
    setLocked(true, "unlock timer expired");
  }

  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wasConnected) {
    Serial.print("Connected to WiFi, IP ");
    Serial.println(WiFi.localIP());
  } else if (!connected && millis() - lastWifiAttempt >= WIFI_RETRY_MS) {
    Serial.println("WiFi down, reconnecting...");
    lastWifiAttempt = millis();
    WiFi.disconnect();
    WiFi.begin(ssid, password);
  }
  wasConnected = connected;

  delay(50);
}
