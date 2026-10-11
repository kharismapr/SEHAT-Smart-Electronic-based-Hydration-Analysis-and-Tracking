#include <Wire.h>
#include <MAX30105.h>

MAX30105 sensor;

uint32_t totalSamples = 0;
uint32_t lastIR = 0;
uint32_t fifoEvents = 0;
uint16_t maxReadCount = 0;
uint8_t lastWritePtr = 0;
uint8_t lastReadPtr = 0;

unsigned long lastDebug = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(21, 22);
  Wire.setClock(100000);

  if (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("ERROR: MAX30102 tidak terdeteksi");
    while (true) delay(1000);
  }

  sensor.setup(0x1F, 1, 2, 50, 411, 4096);
  sensor.disableFIFORollover();

  Serial.println("MAX30102 terdeteksi dan dikonfigurasi");
}

void printRegisters() {
  Serial.printf(
    "MODE=0x%02X | SPO2=0x%02X | FIFO_CFG=0x%02X\n",
    sensor.readRegister8(0x57, 0x09),
    sensor.readRegister8(0x57, 0x0A),
    sensor.readRegister8(0x57, 0x08)
  );

  Serial.printf(
    "LED_RED=0x%02X | LED_IR=0x%02X | SLOT=0x%02X\n",
    sensor.readRegister8(0x57, 0x0C),
    sensor.readRegister8(0x57, 0x0D),
    sensor.readRegister8(0x57, 0x11)
  );
}

void loop() {
  // Periksa apakah FIFO hardware memiliki data sebelum dibaca.
  uint8_t rd = sensor.getReadPointer();
  uint8_t wr = sensor.getWritePointer();

  if (rd != wr) {
    fifoEvents++;
    lastWritePtr = wr;
    lastReadPtr = rd;
  }

  uint16_t n = sensor.check();

  if (n > maxReadCount) {
    maxReadCount = n;
  }

  while (sensor.available()) {
    lastIR = sensor.getFIFOIR();
    totalSamples++;
    sensor.nextSample();
  }
printRegisters();
  if (millis() - lastDebug >= 1000) {
    Serial.printf(
      "PARTID=0x%02X MODE=0x%02X | "
      "FIFO_events=%lu | maxCheck=%u | "
      "totalSamples=%lu | IR=%lu\n",
      sensor.readPartID(),
      sensor.readRegister8(0x57, 0x09),
      (unsigned long)fifoEvents,
      maxReadCount,
      (unsigned long)totalSamples,
      (unsigned long)lastIR
    );

    fifoEvents = 0;
    maxReadCount = 0;
    lastDebug = millis();
  }

  delay(1);
}