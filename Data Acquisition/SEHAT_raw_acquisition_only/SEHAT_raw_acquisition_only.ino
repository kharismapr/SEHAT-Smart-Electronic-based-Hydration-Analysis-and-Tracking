/*
 * SEHAT - RAW DATA ACQUISITION ONLY
 * ESP32 + MAX30102 + Grove GSR + MPU9250
 *
 * Wiring (same as the uploaded firmware):
 *   MAX30102 SDA -> GPIO 21, SCL -> GPIO 22, VCC/GND as required by module
 *   MPU9250 SDA  -> GPIO 21, SCL -> GPIO 22 (shared I2C bus)
 *   Grove GSR SIG -> GPIO 34, VCC/GND as required by module
 *
 * Serial protocol at 115200 baud:
 *   c = calibrate GSR with electrodes/fingers removed from the GSR contacts
 *   s = start raw recording
 *   f = finish recording
 *   r = reset/stop recording (calibration is retained)
 *
 * Output data line:
 * DATA,sample_index,elapsed_us,ppg_ir_raw,gsr_adc12,gsr_adc10,
 *      gsr_conductance_us,gyro_x_dps,gyro_y_dps,gyro_z_dps,gyro_magnitude_dps
 *
 * PPG FIFO samples arrive at 50 Hz. They are linearly interpolated onto the
 * 51.2 Hz GSR time base to preserve aligned PPG/GSR/gyro samples.
 */

#include <Arduino.h>
#include <Wire.h>
#include <MAX30105.h>
#include <math.h>

// ----------------------- PIN & SENSOR CONFIGURATION -----------------------
constexpr uint8_t PIN_SDA = 21;
constexpr uint8_t PIN_SCL = 22;
constexpr uint8_t PIN_GSR = 34;

constexpr uint8_t MAX30102_SAMPLE_RATE_HZ = 50;
constexpr uint8_t MAX30102_LED_BRIGHTNESS = 0x1F;
constexpr uint8_t MAX30102_SAMPLE_AVERAGE = 1;
constexpr uint8_t MAX30102_LED_MODE = 2;       // Red + IR
constexpr uint16_t MAX30102_PULSE_WIDTH = 411;
constexpr uint16_t MAX30102_ADC_RANGE = 4096;

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t GSR_PERIOD_US = 19531;      // 51.2 Hz average; +1 us every fourth interval
constexpr size_t QUEUE_SIZE = 64;

// MPU9250 I2C addresses are tried in this order (AD0 low/high).
constexpr uint8_t MPU_ADDR_CANDIDATES[] = {0x68, 0x69};
constexpr uint8_t MPU_WHO_AM_I_REG = 0x75;
constexpr uint8_t MPU_PWR_MGMT_1 = 0x6B;
constexpr uint8_t MPU_CONFIG = 0x1A;
constexpr uint8_t MPU_GYRO_CONFIG = 0x1B;
constexpr uint8_t MPU_SMPLRT_DIV = 0x19;
constexpr uint8_t MPU_GYRO_XOUT_H = 0x43;
constexpr float MPU_GYRO_LSB_PER_DPS = 131.0f; // +/-250 degrees/second

static MAX30105 ppgSensor;
static uint8_t mpuAddress = 0;
static bool mpuAvailable = false;

// ------------------------------ DATA TYPES --------------------------------
struct GyroAxes {
  float x;
  float y;
  float z;
};

struct PpgPoint {
  float ir;
  GyroAxes gyro;
};

struct GsrPoint {
  float adc12;
  float adc10;
  float conductanceUs;
};

static GsrPoint gsrQueue[QUEUE_SIZE];
static PpgPoint ppgQueue[QUEUE_SIZE];

static uint64_t gsrProduced = 0;
static uint64_t ppgProduced = 0;
static uint64_t pairedCount = 0;
static uint64_t rawPpgIndex = 0;

static uint32_t nextGsrUs = 0;
static uint32_t lastPpgMillis = 0;
static float previousIr = NAN;
static GyroAxes previousGyro = {NAN, NAN, NAN};
static float gsrCalibrationAdc10 = NAN;

static bool recordingRequested = false;
static bool recording = false;
static bool gsrCalibrated = false;
static uint32_t missedGsrSamples = 0;

// ------------------------------ MPU9250 -----------------------------------
bool mpuWriteRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool mpuReadRegisters(uint8_t reg, uint8_t *buffer, size_t length) {
  Wire.beginTransmission(mpuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;

  const size_t received = Wire.requestFrom((int)mpuAddress, (int)length);
  if (received != length) {
    while (Wire.available()) Wire.read();
    return false;
  }
  for (size_t i = 0; i < length; ++i) buffer[i] = Wire.read();
  return true;
}

bool initializeMpu9250() {
  for (uint8_t candidate : MPU_ADDR_CANDIDATES) {
    mpuAddress = candidate;
    uint8_t who = 0;
    if (mpuReadRegisters(MPU_WHO_AM_I_REG, &who, 1) &&
        (who == 0x71 || who == 0x73)) {
      mpuAvailable = true;
      break;
    }
  }

  if (!mpuAvailable) return false;

  // Wake device, enable a modest digital low-pass filter, and select +/-250 dps.
  if (!mpuWriteRegister(MPU_PWR_MGMT_1, 0x00)) return false;
  delay(100);
  if (!mpuWriteRegister(MPU_CONFIG, 0x03)) return false;
  if (!mpuWriteRegister(MPU_GYRO_CONFIG, 0x00)) return false;
  if (!mpuWriteRegister(MPU_SMPLRT_DIV, 0x04)) return false;
  delay(20);
  return true;
}

GyroAxes readGyroDps() {
  GyroAxes axes = {NAN, NAN, NAN};
  if (!mpuAvailable) return axes;

  uint8_t bytes[6];
  if (!mpuReadRegisters(MPU_GYRO_XOUT_H, bytes, sizeof(bytes))) return axes;

  const int16_t gx = (int16_t)((bytes[0] << 8) | bytes[1]);
  const int16_t gy = (int16_t)((bytes[2] << 8) | bytes[3]);
  const int16_t gz = (int16_t)((bytes[4] << 8) | bytes[5]);
  axes.x = (float)gx / MPU_GYRO_LSB_PER_DPS;
  axes.y = (float)gy / MPU_GYRO_LSB_PER_DPS;
  axes.z = (float)gz / MPU_GYRO_LSB_PER_DPS;
  return axes;
}

float gyroMagnitude(const GyroAxes &g) {
  if (!isfinite(g.x) || !isfinite(g.y) || !isfinite(g.z)) return NAN;
  return sqrtf(g.x * g.x + g.y * g.y + g.z * g.z);
}

// ------------------------------- GSR --------------------------------------
uint16_t readGsrAdc12() {
  return (uint16_t)analogRead(PIN_GSR);
}

float adc12ToAdc10(uint16_t adc12) {
  return (float)adc12 * (1023.0f / 4095.0f);
}

GsrPoint readGsrPoint() {
  GsrPoint point;
  point.adc12 = (float)readGsrAdc12();
  point.adc10 = point.adc12 * (1023.0f / 4095.0f);

  const float delta = gsrCalibrationAdc10 - point.adc10;
  if (!isfinite(gsrCalibrationAdc10) || !isfinite(point.adc10) || delta <= 0.0f) {
    point.conductanceUs = NAN;
    return point;
  }

  // Same Grove GSR conversion used in the uploaded firmware.
  const float resistanceOhm = ((1024.0f + 2.0f * point.adc10) * 10000.0f) / delta;
  point.conductanceUs = (isfinite(resistanceOhm) && resistanceOhm > 0.0f)
      ? 1000000.0f / resistanceOhm : NAN;
  return point;
}

void calibrateGsrWithoutContact() {
  recording = false;
  recordingRequested = false;
  Serial.println("INFO,GSR_CALIBRATION_STARTED,remove_contact");

  float sum = 0.0f;
  constexpr uint8_t CALIBRATION_SAMPLES = 32;
  for (uint8_t i = 0; i < CALIBRATION_SAMPLES; ++i) {
    sum += adc12ToAdc10(readGsrAdc12());
    delay(5);
  }
  gsrCalibrationAdc10 = sum / CALIBRATION_SAMPLES;
  gsrCalibrated = isfinite(gsrCalibrationAdc10);

  Serial.printf("INFO,GSR_CALIBRATION_DONE,adc10=%.3f\n", gsrCalibrationAdc10);
}

// -------------------------- SYNCHRONIZED QUEUES ---------------------------
void clearPpgFifo() {
  while (ppgSensor.available()) ppgSensor.nextSample();
  ppgSensor.clearFIFO();
}

void stopRecording(const char *reason) {
  const uint64_t savedSamples = recording ? pairedCount : 0;
  recording = false;
  recordingRequested = false;
  Serial.printf("INFO,RECORDING_STOPPED,%s,samples=%llu,missed_gsr=%lu\n",
                reason,
                (unsigned long long)savedSamples,
                (unsigned long)missedGsrSamples);
}

bool queueGsr(const GsrPoint &point) {
  if (gsrProduced - pairedCount >= QUEUE_SIZE) return false;
  gsrQueue[gsrProduced % QUEUE_SIZE] = point;
  ++gsrProduced;
  return true;
}

bool queuePpg(const PpgPoint &point) {
  if (ppgProduced - pairedCount >= QUEUE_SIZE) return false;
  ppgQueue[ppgProduced % QUEUE_SIZE] = point;
  ++ppgProduced;
  return true;
}

void drainPairedSamples() {
  while (recording && pairedCount < gsrProduced && pairedCount < ppgProduced) {
    const size_t slot = (size_t)(pairedCount % QUEUE_SIZE);
    const GsrPoint &g = gsrQueue[slot];
    const PpgPoint &p = ppgQueue[slot];
    const uint64_t elapsedUs = (pairedCount * 1953125ULL) / 100ULL;

    Serial.printf("DATA,%llu,%llu,%.3f,%.0f,%.3f,%.6f,%.4f,%.4f,%.4f,%.4f\n",
                  (unsigned long long)pairedCount,
                  (unsigned long long)elapsedUs,
                  p.ir,
                  g.adc12,
                  g.adc10,
                  g.conductanceUs,
                  p.gyro.x,
                  p.gyro.y,
                  p.gyro.z,
                  gyroMagnitude(p.gyro));
    ++pairedCount;
  }
}

void startRecordingWithFirstPpg(float ir, const GyroAxes &gyro) {
  gsrProduced = 0;
  ppgProduced = 0;
  pairedCount = 0;
  rawPpgIndex = 0;
  missedGsrSamples = 0;
  previousIr = ir;
  previousGyro = gyro;
  lastPpgMillis = millis();
  nextGsrUs = micros() + GSR_PERIOD_US;
  recording = true;

  const GsrPoint firstGsr = readGsrPoint();
  const PpgPoint firstPpg = {ir, gyro};
  if (!queueGsr(firstGsr) || !queuePpg(firstPpg)) {
    stopRecording("initial_queue_error");
    return;
  }
  Serial.println("INFO,RECORDING_STARTED,fs_hz=51.2,ppg_source_hz=50");
  drainPairedSamples();
}

void sampleGsrAtScheduledTime() {
  while (recording) {
    const int32_t lateness = (int32_t)(micros() - nextGsrUs);
    if (lateness < 0) return;

    GsrPoint point;
    if (lateness < (int32_t)GSR_PERIOD_US) {
      point = readGsrPoint();
    } else {
      point.adc12 = NAN;
      point.adc10 = NAN;
      point.conductanceUs = NAN;
      ++missedGsrSamples;
    }

    if (!queueGsr(point)) {
      stopRecording("gsr_queue_overflow");
      return;
    }

    // GSR time base: 19531.25 us on average.
    nextGsrUs += GSR_PERIOD_US + ((gsrProduced % 4ULL) == 0ULL ? 1UL : 0UL);
    drainPairedSamples();
  }
}

void handlePpgSample(uint32_t rawIr) {
  const float ir = (rawIr == 0 || rawIr >= 0x3FFFFUL) ? NAN : (float)rawIr;
  const GyroAxes gyro = readGyroDps();

  if (!recording) {
    if (recordingRequested) startRecordingWithFirstPpg(ir, gyro);
    return;
  }

  ++rawPpgIndex;
  lastPpgMillis = millis();

  // Convert 50-Hz PPG/gyro samples to the shared 51.2-Hz sample index.
  // Ratio 50/51.2 is exactly 125/128.
  while (recording && ppgProduced * 125ULL <= rawPpgIndex * 128ULL) {
    const double fraction = (double)(ppgProduced * 125ULL - (rawPpgIndex - 1ULL) * 128ULL) / 128.0;
    PpgPoint point;
    point.ir = (isfinite(ir) && isfinite(previousIr))
        ? previousIr + (float)(fraction * (ir - previousIr)) : NAN;

    point.gyro.x = (isfinite(gyro.x) && isfinite(previousGyro.x))
        ? previousGyro.x + (float)(fraction * (gyro.x - previousGyro.x)) : NAN;
    point.gyro.y = (isfinite(gyro.y) && isfinite(previousGyro.y))
        ? previousGyro.y + (float)(fraction * (gyro.y - previousGyro.y)) : NAN;
    point.gyro.z = (isfinite(gyro.z) && isfinite(previousGyro.z))
        ? previousGyro.z + (float)(fraction * (gyro.z - previousGyro.z)) : NAN;

    if (!queuePpg(point)) {
      stopRecording("ppg_queue_overflow");
      return;
    }
    drainPairedSamples();
  }

  previousIr = ir;
  previousGyro = gyro;
}

// -------------------------------- SETUP ------------------------------------
void configureMax30102() {
  ppgSensor.setup(MAX30102_LED_BRIGHTNESS,
                  MAX30102_SAMPLE_AVERAGE,
                  MAX30102_LED_MODE,
                  MAX30102_SAMPLE_RATE_HZ,
                  MAX30102_PULSE_WIDTH,
                  MAX30102_ADC_RANGE);
  delay(50);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_GSR, ADC_11db);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);

  if (!ppgSensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("ERROR,MAX30102_NOT_DETECTED,check_power_sda_scl");
    while (true) delay(1000);
  }
  configureMax30102();

  mpuAvailable = initializeMpu9250();
  Serial.printf("INFO,READY,MAX30102=1,MPU9250=%d,MPU_ADDR=0x%02X,GSR_PIN=%u\n",
                mpuAvailable ? 1 : 0,
                mpuAvailable ? mpuAddress : 0,
                PIN_GSR);
  Serial.println("INFO,COMMANDS,c=calibrate_GSR,s=start,f=finish,r=reset");
}

// --------------------------------- LOOP ------------------------------------
void loop() {
  while (Serial.available() > 0) {
    const char command = (char)Serial.read();
    if (command == 'c' || command == 'C') {
      calibrateGsrWithoutContact();
    } else if (command == 's' || command == 'S') {
      if (!gsrCalibrated) {
        Serial.println("ERROR,GSR_NOT_CALIBRATED,send_c_first");
      } else {
        stopRecording("new_recording");
        clearPpgFifo();
        configureMax30102();
        recordingRequested = true;
        Serial.println("INFO,WAITING_FOR_FIRST_PPG_SAMPLE");
      }
    } else if (command == 'f' || command == 'F') {
      stopRecording("user_finished");
    } else if (command == 'r' || command == 'R') {
      stopRecording("user_reset");
      recordingRequested = false;
      clearPpgFifo();
      Serial.println("INFO,RESET_DONE,gsr_calibration_retained");
    }
  }

  const uint16_t newSamples = ppgSensor.check();

  if (recording && millis() - lastPpgMillis > 250) {
    stopRecording("ppg_timeout");
  } else if (recording && newSamples >= 32) {
    clearPpgFifo();
    stopRecording("max30102_fifo_backlog");
  }

  while (ppgSensor.available()) {
    const uint32_t ir = ppgSensor.getFIFOIR();
    ppgSensor.nextSample();
    if (recordingRequested || recording) handlePpgSample(ir);
    if (recording) sampleGsrAtScheduledTime();
  }

  if (recording) sampleGsrAtScheduledTime();
}
