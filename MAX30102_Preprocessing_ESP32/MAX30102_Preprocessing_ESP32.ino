// SEHAT: MAX30102 PPG preprocessing with GY-9250 (MPU-9250) on ESP32.
// Open this .ino in Arduino IDE; keep ppg_preprocessing_esp32.h beside it.
// Install "SparkFun MAX3010x Pulse and Proximity Sensor Library".

#include <Arduino.h>
#include <Wire.h>
#include <MAX30105.h>  // SparkFun uses this name for MAX30102 as well
#include "ppg_preprocessing_esp32.h"

// ESP32 DevKit defaults. Change for the actual ESP32 board/wiring.
constexpr int kSdaPin = 21;
constexpr int kSclPin = 22;
constexpr uint32_t kSensorHz = 50;

static MAX30105 max30102;
static sehat_ppg::Processor ppg;  // global; its buffers are too large for loop() stack
static uint64_t raw_index = 0;
static uint64_t output_index = 0;
static float previous_ir = NAN;
struct GyroAxes { float x, y, z; };
static GyroAxes previous_gyro = {NAN, NAN, NAN};
static bool have_previous = false;
static uint32_t last_raw_ms = 0;
static uint8_t gyro_address = 0;  // 0x68 or 0x69; zero means unavailable

// MPU-9250 register map (TDK InvenSense RM-MPU-9250A-00).
constexpr uint8_t kWhoAmI = 0x75;
constexpr uint8_t kPowerManagement1 = 0x6B;
constexpr uint8_t kPowerManagement2 = 0x6C;
constexpr uint8_t kSampleRateDivider = 0x19;
constexpr uint8_t kConfiguration = 0x1A;
constexpr uint8_t kGyroConfiguration = 0x1B;
constexpr uint8_t kGyroXoutHigh = 0x43;

bool readGyroRegister(uint8_t address, uint8_t reg, uint8_t& value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(address, static_cast<uint8_t>(1)) != 1 ||
      Wire.available() < 1) return false;
  value = static_cast<uint8_t>(Wire.read());
  return true;
}

bool writeGyroRegister(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool beginGyro() {
  uint8_t identity = 0;
  const uint8_t candidate_addresses[2] = {0x68, 0x69};
  for (uint8_t address : candidate_addresses) {
    if (!readGyroRegister(address, kWhoAmI, identity)) continue;
    if (identity == 0x71) {
      gyro_address = address;
      break;
    }
    Serial.printf("I2C 0x%02X: WHO_AM_I=0x%02X (MPU-9250 expects 0x71).\n",
                  address, identity);
  }
  if (!gyro_address) return false;

  // Wake and select gyro PLL; DLPF_CFG=3 (~41 Hz), ODR=1000/(1+9)=100 Hz.
  // Gyro FS_SEL=1: +/-500 deg/s, 65.5 LSB/(deg/s), like the paper's IMU range.
  bool ok = writeGyroRegister(gyro_address, kPowerManagement1, 0x80);
  delay(100);
  ok = writeGyroRegister(gyro_address, kPowerManagement1, 0x01) && ok;
  delay(50);
  ok = writeGyroRegister(gyro_address, kPowerManagement2, 0x00) && ok;
  ok = writeGyroRegister(gyro_address, kConfiguration, 0x03) && ok;
  ok = writeGyroRegister(gyro_address, kSampleRateDivider, 0x09) && ok;
  ok = writeGyroRegister(gyro_address, kGyroConfiguration, 0x08) && ok;
  uint8_t configured_range = 0;
  ok = readGyroRegister(gyro_address, kGyroConfiguration,
                        configured_range) && ok && configured_range == 0x08;
  if (!ok) gyro_address = 0;
  return ok;
}

// Read the latest gyro sample near each MAX30102 FIFO observation. Return NaN
// on I2C failure; short holes can be repaired by the preprocessing class.
GyroAxes readGyroAxes() {
  if (!gyro_address) return {NAN, NAN, NAN};
  Wire.beginTransmission(gyro_address);
  Wire.write(kGyroXoutHigh);
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(gyro_address, static_cast<uint8_t>(6)) != 6 ||
      Wire.available() < 6) return {NAN, NAN, NAN};
  uint8_t bytes[6];
  for (uint8_t& byte : bytes) byte = static_cast<uint8_t>(Wire.read());
  const int16_t x = static_cast<int16_t>(
      (static_cast<uint16_t>(bytes[0]) << 8) | bytes[1]);
  const int16_t y = static_cast<int16_t>(
      (static_cast<uint16_t>(bytes[2]) << 8) | bytes[3]);
  const int16_t z = static_cast<int16_t>(
      (static_cast<uint16_t>(bytes[4]) << 8) | bytes[5]);
  return {x / 65.5f, y / 65.5f, z / 65.5f};  // degrees per second
}

float gyroMagnitude(const GyroAxes& axes) {
  if (!std::isfinite(axes.x) || !std::isfinite(axes.y) ||
      !std::isfinite(axes.z)) return NAN;
  return std::sqrt(axes.x * axes.x + axes.y * axes.y + axes.z * axes.z);
}

void resetRecording(const char* reason) {
  ppg.reset();
  raw_index = output_index = 0;
  have_previous = false;
  previous_ir = NAN;
  previous_gyro = {NAN, NAN, NAN};
  last_raw_ms = 0;
  max30102.clearFIFO();
  Serial.println(reason);
}

void printFeatures(const sehat_ppg::Features& f) {
  Serial.printf("status=%s,ppg_available=%u,mean_hr=%.3f,rmssd=%.3f,"
                "sdnn=%.3f,pnn50=%.3f,n_peaks=%u,ibi=%.3f,"
                "gyro_missing=%.3f,high_motion=%.3f,"
                "ppg_interpolated=%.3f,rr_rejected=%.3f,window_samples=%u\n",
                sehat_ppg::statusName(f.status),
                static_cast<unsigned>(f.ppg_available),
                f.mean_hr, f.rmssd, f.sdnn, f.pnn50,
                static_cast<unsigned>(f.n_peaks), f.ibi,
                f.gyro_missing_fraction, f.high_motion_fraction,
                f.ppg_interpolated_fraction, f.rr_rejected_fraction,
                static_cast<unsigned>(f.window_samples));
}

void addAlignedSample(float ir, float gyro_magnitude) {
  sehat_ppg::Features features;
  if (ppg.addSample(ir, gyro_magnitude, features)) printFeatures(features);
}

// The MAX30102 supports 50 Hz, not the training data's 51.2 Hz. Linear
// interpolation at exact rational positions (50/51.2 = 125/128) produces
// 51.2-Hz inputs for the filter and the 30-second, 1536-sample window.
void addSensorSample(float ir, const GyroAxes& gyro_axes) {
  if (!have_previous) {
    addAlignedSample(ir, gyroMagnitude(gyro_axes));  // t = 0
    previous_ir = ir;
    previous_gyro = gyro_axes;
    have_previous = true;
    output_index = 1;
    return;
  }
  ++raw_index;
  while (output_index * 125ULL <= raw_index * 128ULL) {
    const double fraction = static_cast<double>(
        output_index * 125ULL - (raw_index - 1ULL) * 128ULL) / 128.0;
    const float aligned_ir = std::isfinite(ir) && std::isfinite(previous_ir)
        ? previous_ir + static_cast<float>(fraction * (ir - previous_ir)) : NAN;
    const GyroAxes aligned_axes = {
      previous_gyro.x + static_cast<float>(fraction *
          (gyro_axes.x - previous_gyro.x)),
      previous_gyro.y + static_cast<float>(fraction *
          (gyro_axes.y - previous_gyro.y)),
      previous_gyro.z + static_cast<float>(fraction *
          (gyro_axes.z - previous_gyro.z))
    };
    addAlignedSample(aligned_ir, gyroMagnitude(aligned_axes));
    ++output_index;
  }
  previous_ir = ir;
  previous_gyro = gyro_axes;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(kSdaPin, kSclPin);
  Wire.setClock(400000);
  if (!max30102.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 tidak ditemukan. Periksa SDA, SCL, 3V3, GND.");
    while (true) delay(1000);
  }
  // No FIFO averaging: every FIFO sample represents one 50-Hz observation.
  // LED mode 2 enables red + IR; IR is used for the PPG waveform.
  max30102.setup(0x1F, 1, 2, kSensorHz, 411, 4096);
  max30102.disableFIFORollover();
  if (beginGyro()) {
    Serial.printf("MPU-9250 ready at I2C 0x%02X; gyro at 100 Hz, +/-500 dps.\n",
                  gyro_address);
  } else {
    Serial.println("MPU-9250 not found/configured (WHO_AM_I must be 0x71).");
    Serial.println("PPG continues with the 4 Hz low-motion filter.");
  }
  Serial.println("MAX30102 ready: IR 50 Hz -> 51.2 Hz; window 30 s/50% overlap.");
  Serial.println("PPG HRV uses an embedded peak detector, not HeartPy.");
  Serial.println("Send 'f' to emit the partial tail; 'r' to reset the recording.");
}

void loop() {
  while (Serial.available()) {
    const char command = static_cast<char>(Serial.read());
    if (command == 'r' || command == 'R') resetRecording("Recording reset.");
    if (command == 'f' || command == 'F') {
      sehat_ppg::Features tail;
      if (ppg.flush(tail)) printFeatures(tail);
      resetRecording("Partial tail emitted; new recording started.");
    }
  }

  const uint16_t read_count = max30102.check();
  // SparkFun's in-memory FIFO has only four slots. More than three new
  // samples can overwrite data before it is consumed; never stitch that gap.
  if (read_count > 3) {
    resetRecording("FIFO backlog: samples lost, window reset.");
    return;
  }
  if (!read_count && have_previous && millis() - last_raw_ms > 100) {
    resetRecording("PPG timing gap >100 ms, window reset.");
    return;
  }
  if (!max30102.available()) { delay(1); return; }

  while (max30102.available()) {
    const uint32_t ir_counts = max30102.getFIFOIR();
    max30102.nextSample();
    const uint32_t now = millis();
    if (have_previous && now - last_raw_ms > 100) {
      resetRecording("PPG timing gap >100 ms, window reset.");
      return;
    }
    last_raw_ms = now;
    const float ir = ir_counts == 0 || ir_counts >= 0x3FFFF
        ? NAN : static_cast<float>(ir_counts);
    addSensorSample(ir, readGyroAxes());
  }
}
