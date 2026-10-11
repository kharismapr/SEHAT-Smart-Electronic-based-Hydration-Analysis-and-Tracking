#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <cmath>

namespace sehat_gyro {

struct Axes { float x, y, z; };
static uint8_t address = 0;

inline bool readRegister(uint8_t device, uint8_t reg, uint8_t& value) {
  Wire.beginTransmission(device);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(device, static_cast<uint8_t>(1)) != 1 ||
      Wire.available() < 1) return false;
  value = static_cast<uint8_t>(Wire.read());
  return true;
}

inline bool writeRegister(uint8_t device, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(device);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

inline bool begin() {
  uint8_t identity = 0;
  const uint8_t candidates[2] = {0x68, 0x69};
  for (uint8_t device : candidates) {
    if (readRegister(device, 0x75, identity) && identity == 0x71) {
      address = device;
      break;
    }
  }
  if (!address) return false;
  bool ok = writeRegister(address, 0x6B, 0x80);
  delay(100);  // Setup only, before acquisition.
  ok = writeRegister(address, 0x6B, 0x01) && ok;
  delay(50);
  ok = writeRegister(address, 0x6C, 0x00) && ok;
  ok = writeRegister(address, 0x1A, 0x03) && ok;
  ok = writeRegister(address, 0x19, 0x09) && ok;
  ok = writeRegister(address, 0x1B, 0x08) && ok;  // +/-500 dps.
  uint8_t range = 0;
  ok = readRegister(address, 0x1B, range) && ok && range == 0x08;
  if (!ok) address = 0;
  return ok;
}

inline Axes read() {
  if (!address) return {NAN, NAN, NAN};
  Wire.beginTransmission(address);
  Wire.write(static_cast<uint8_t>(0x43));
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(address, static_cast<uint8_t>(6)) != 6 ||
      Wire.available() < 6) return {NAN, NAN, NAN};
  uint8_t b[6];
  for (uint8_t& item : b) item = static_cast<uint8_t>(Wire.read());
  const int16_t x = static_cast<int16_t>((uint16_t(b[0]) << 8) | b[1]);
  const int16_t y = static_cast<int16_t>((uint16_t(b[2]) << 8) | b[3]);
  const int16_t z = static_cast<int16_t>((uint16_t(b[4]) << 8) | b[5]);
  return {x / 65.5f, y / 65.5f, z / 65.5f};
}

inline float magnitude(const Axes& axes) {
  return std::isfinite(axes.x) && std::isfinite(axes.y) &&
         std::isfinite(axes.z)
      ? std::sqrt(axes.x * axes.x + axes.y * axes.y + axes.z * axes.z)
      : NAN;
}

}  // namespace sehat_gyro
