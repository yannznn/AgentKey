#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH     128
#define SCREEN_HEIGHT     64
#define OLED_RESET        -1
#define OLED_SDA           8
#define OLED_SCL           9

#define TOUCH_PIN         10   // Connected to sensor TOUCH_OUT

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

bool authPending = false;
String pendingAction = "";
unsigned long authStartTime = 0;
const unsigned long AUTH_TIMEOUT_MS = 15000;

void showStatus(const char* title, const char* line1, const char* line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(title);
  display.drawLine(0, 12, 128, 12, SSD1306_WHITE);
  display.setCursor(0, 24);
  display.println(line1);
  display.setCursor(0, 44);
  display.println(line2);
  display.display();
}

void setup() {
  Serial.begin(115200);

  // Configure hardware capacitive touch pin with pulldown
  pinMode(TOUCH_PIN, INPUT_PULLDOWN);

  Wire.begin(OLED_SDA, OLED_SCL);
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    display.clearDisplay();
    showStatus("<< MCP GATEWAY >>", "Status: IDLE", "Waiting for Agent...");
  }
}

void loop() {
  // 1. Listen for auth challenges from host Python gateway
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (input.startsWith("AUTH_REQ:")) {
      pendingAction = input.substring(9);
      authPending = true;
      authStartTime = millis();

      char actionBuf[24];
      pendingAction.toCharArray(actionBuf, 24);
      showStatus("<< HITL REQ >>", actionBuf, "Touch Sensor...");
    }
  }

  // 2. Hardware verification window
  if (authPending) {
    // Timeout condition
    if (millis() - authStartTime > AUTH_TIMEOUT_MS) {
      Serial.println("AUTH_TIMEOUT:NONE");
      Serial.flush();
      showStatus("<< TIMEOUT >>", "Action Rejected", "Returning Idle...");
      authPending = false;
      delay(1800);
      showStatus("<< MCP GATEWAY >>", "Status: IDLE", "Waiting for Agent...");
      return;
    }

    // Hardware touch detection
    if (digitalRead(TOUCH_PIN) == HIGH) {
      delay(40); // Debounce
      if (digitalRead(TOUCH_PIN) == HIGH) {
        // Generate hardware-bound token identity via unique ESP32-S3 eFuse MAC
        uint32_t chipId = (uint32_t)ESP.getEfuseMac();
        char authSignature[64];
        snprintf(authSignature, sizeof(authSignature), "AUTH_OK:ESP32S3_%06X:ADMIN_OPERATOR", chipId & 0xFFFFFF);

        Serial.println(authSignature);
        Serial.flush();

        showStatus("<< APPROVED >>", "Touch Verified", "Signing Request...");
        authPending = false;
        delay(2000);
        showStatus("<< MCP GATEWAY >>", "Status: IDLE", "Waiting for Agent...");
      }
    }

    delay(20);
  }
}