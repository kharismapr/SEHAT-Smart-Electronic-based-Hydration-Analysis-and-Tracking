/*
  SEHAT Firmware: MAX30102 Diagnostic & Connectivity Test
  Target Board: Seeed Studio XIAO ESP32-C3
  Sensor: MAX30102 (Pulse Oximeter & Heart Rate Sensor via I2C)

  Required Arduino Library:
  - "SparkFun MAX3010x Pulse and Proximity Sensor Library" by SparkFun
    (Install via Arduino IDE Library Manager)

  Pinout Wiring for XIAO ESP32-C3:
  ┌───────────────┬───────────────────────────────┐
  │ MAX30102 Pin  │ XIAO ESP32-C3 Pin (Default)   │
  ├───────────────┼───────────────────────────────┤
  │ VIN / VCC     │ 3.3V                          │
  │ GND           │ GND                           │
  │ SDA           │ D4 / GPIO6 (SDA)              │
  │ SCL           │ D5 / GPIO7 (SCL)              │
  │ INT           │ Not connected (optional)      │
  └───────────────┴───────────────────────────────┘
*/

#include <Wire.h>
#include "MAX30105.h"

// MAX30105 library handles both MAX30102 and MAX30105
MAX30105 particleSensor;

// Pin definitions for Seeed Studio XIAO ESP32-C3 default I2C
#define I2C_SDA D4 // GPIO 6
#define I2C_SCL D5 // GPIO 7

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000); // Wait for Serial Monitor

  Serial.println("\n==========================================");
  Serial.println("   SEHAT: MAX30102 Diagnostic Test");
  Serial.println("   Target: XIAO ESP32-C3");
  Serial.println("==========================================\n");

  // 1. Initialize I2C Bus on XIAO ESP32-C3
  Serial.print("[I2C] Initializing I2C Bus (SDA: D4, SCL: D5)... ");
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("OK");

  // 2. Initialize MAX30102 Sensor
  Serial.print("[Sensor] Probing MAX30102 on I2C address 0x57... ");
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("\n[ERROR] MAX30102 was not found!");
    Serial.println("  -> Check your wiring (3.3V, GND, D4/SDA, D5/SCL).");
    Serial.println("  -> Verify if your module has 3.3V pull-up resistors.");
    while (1) {
      delay(1000);
    }
  }
  Serial.println("FOUND!");

  // 3. Configure Sensor for Continuous PPG (Red + IR) Reading
  byte ledBrightness = 0x1F; // Options: 0=Off to 255=50mA (0x1F ~ 6.4mA)
  byte sampleAverage = 4;    // Options: 1, 2, 4, 8, 16, 32
  byte ledMode = 2;          // Options: 1 = Red only, 2 = Red + IR, 3 = Red + IR + Green
  int sampleRate = 400;      // Options: 50, 100, 200, 400, 800, 1000, 1600, 3200
  int pulseWidth = 411;      // Options: 69, 118, 215, 411
  int adcRange = 4096;       // Options: 2048, 4096, 8192, 16384

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);

  // Enable internal die temperature read
  particleSensor.enableDIETEMPRDY();

  Serial.println("\n[Ready] Place your finger gently on the sensor.");
  Serial.println("Printing: IR_Value, Red_Value, Temperature_C");
  Serial.println("----------------------------------------------");
}

void loop() {
  // Read Photoplethysmography (PPG) Raw Signals
  uint32_t irValue = particleSensor.getIR();
  uint32_t redValue = particleSensor.getRed();

  // Finger detection threshold
  if (irValue < 50000) {
    Serial.print("IR: ");
    Serial.print(irValue);
    Serial.println("  [NO FINGER DETECTED - Place finger on glass]");
  } else {
    // Read internal die temperature (°C)
    float temperatureC = particleSensor.readTemperature();

    // Serial Plotter / Monitor compatible output
    Serial.print("IR:");
    Serial.print(irValue);
    Serial.print(",Red:");
    Serial.print(redValue);
    Serial.print(",Temp_C:");
    Serial.println(temperatureC, 2);
  }

  delay(20); // ~50 Hz sampling rate for clear signal inspection
}
