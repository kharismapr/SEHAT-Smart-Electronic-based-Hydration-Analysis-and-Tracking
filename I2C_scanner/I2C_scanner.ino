#include <Wire.h>

// I2C pins for esp32
#define SDA_PIN D4
#define SCL_PIN D5

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10); // Wait for Serial Monitor connection
  }

  Serial.println("\n--- I2C Scanner (XIAO ESP32-C3) ---");
  Wire.begin(SDA_PIN, SCL_PIN);
}

void loop() {
  byte error, address;
  int nDevices = 0;

  Serial.println("Scanning I2C bus...");

  for (address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("Device found at address 0x");
      if (address < 16) Serial.print("0");
      Serial.print(address, HEX);

      // Identify common MAX30102 / MAX30105 sensor address
      if (address == 0x57) {
        Serial.print("  <-- MAX30102 Heart Rate Sensor");
      }
      Serial.println();

      nDevices++;
    } else if (error == 4) {
      Serial.print("Unknown error at address 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
    }
  }

  if (nDevices == 0) {
    Serial.println("No I2C devices found. Check wiring and power connections.\n");
  } else {
    Serial.println("Scan finished.\n");
  }

  delay(5000); // Rescan every 5 seconds
}