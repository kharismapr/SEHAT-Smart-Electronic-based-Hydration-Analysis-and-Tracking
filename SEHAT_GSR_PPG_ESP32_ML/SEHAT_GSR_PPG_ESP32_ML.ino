// SEHAT S1: synchronized GSR/PPG preprocessing and ExtraTrees regression.
// Model output is fasting_duration_hr (hours), not hydration percentage.
#include <Arduino.h>
#include <Wire.h>
#include <MAX30105.h>
#include <cmath>

#include "mpu9250_gyro.h"
#include "s1_features.h"
typedef float float32;  // Type required by the checked-in emlearn export.
#include "et_hydration_model_S1.h"

constexpr uint8_t kSdaPin = 21, kSclPin = 22, kGsrPin = 34;
constexpr uint8_t kSensorHz = 50;
constexpr uint32_t kGsrPeriodUs = 19531;  // 51.2 Hz; add 1 us every fourth tick.
constexpr size_t kPending = 64;

static MAX30105 max30102;
static sehat_gsr::Processor gsr;
static sehat_ppg::Processor ppg;
struct PpgPoint { float ir, gyro; };
static float gsr_queue[kPending];
static PpgPoint ppg_queue[kPending];
static uint64_t gsr_produced = 0, ppg_produced = 0, paired = 0, raw_index = 0;
static uint32_t next_gsr_us = 0, last_ppg_ms = 0, window_number = 0;
static float previous_ir = NAN, calibration_adc10 = NAN;
static sehat_gyro::Axes previous_gyro = {NAN, NAN, NAN};
static bool active = false, acquisition_enabled = false;

float readGroveAdc10() {
  return static_cast<float>(analogRead(kGsrPin)) * (1023.0f / 4095.0f);
}

// Seeed Grove no-finger calibration -> skin resistance -> conductance in uS.
float readGsrUs() {
  const float adc10 = readGroveAdc10();
  const float delta = calibration_adc10 - adc10;
  if (!std::isfinite(calibration_adc10) || !std::isfinite(adc10) ||
      delta <= 0.0f) return NAN;
  const float resistance_ohm =
      ((1024.0f + 2.0f * adc10) * 10000.0f) / delta;
  return std::isfinite(resistance_ohm) && resistance_ohm > 0.0f
      ? 1000000.0f / resistance_ohm : NAN;
}

void resetRecording(const char* reason) {
  active = false;
  acquisition_enabled = false;
  gsr.reset();
  ppg.reset();
  gsr_produced = ppg_produced = paired = raw_index = 0;
  previous_ir = NAN;
  previous_gyro = {NAN, NAN, NAN};
  max30102.clearFIFO();
  Serial.println(reason);
}

void reportWindow(const sehat_gsr::Features& g,
                  const sehat_ppg::Features& p) {
  ++window_number;
  float input[sehat_s1::feature_count] = {};
  if (!sehat_s1::makeModelInput(g, p, input)) {
    Serial.printf("Window %lu: no prediction (invalid GSR or feature vector).\n",
                  static_cast<unsigned long>(window_number));
    return;
  }
  const float hours = hydration_et_predict(input, sehat_s1::feature_count);
  if (!std::isfinite(hours)) {
    Serial.printf("Window %lu: no prediction (non-finite model output).\n",
                  static_cast<unsigned long>(window_number));
    return;
  }
  Serial.printf("Window %lu: experimental S1 fasting-duration estimate = %.3f hours; "
                "PPG available=%u; GSR interpolated=%u/%u; PPG status=%s\n",
                static_cast<unsigned long>(window_number), hours,
                static_cast<unsigned>(input[sehat_s1::ppg_available]),
                static_cast<unsigned>(g.interpolated_samples),
                static_cast<unsigned>(g.window_samples),
                sehat_ppg::statusName(p.status));
}

void addPairedSample(float conductance_us, const PpgPoint& point) {
  sehat_gsr::Features g;
  sehat_ppg::Features p;
  const bool g_ready = gsr.addSample(conductance_us, g);
  const bool p_ready = ppg.addSample(point.ir, point.gyro, p);
  if (g_ready != p_ready) {
    resetRecording("Window synchronization lost; recording reset.");
    return;
  }
  if (g_ready) reportWindow(g, p);
}

void drainPairs() {
  while (active && paired < gsr_produced && paired < ppg_produced) {
    const size_t slot = static_cast<size_t>(paired % kPending);
    addPairedSample(gsr_queue[slot], ppg_queue[slot]);
    if (!active) return;
    ++paired;
  }
}

bool queueGsr(float value) {
  if (gsr_produced - paired >= kPending) return false;
  gsr_queue[gsr_produced % kPending] = value;
  ++gsr_produced;
  return true;
}

bool queuePpg(float ir, float gyro) {
  if (ppg_produced - paired >= kPending) return false;
  ppg_queue[ppg_produced % kPending] = {ir, gyro};
  ++ppg_produced;
  return true;
}

// A missed GSR ADC instant is represented as NaN at its scheduled index.
// The GSR extractor interpolates finite gaps as in the training pipeline.
void sampleGsrDue() {
  while (active) {
    const int32_t late = static_cast<int32_t>(micros() - next_gsr_us);
    if (late < 0) return;
    const float value = late < static_cast<int32_t>(kGsrPeriodUs)
        ? readGsrUs() : NAN;
    if (!queueGsr(value)) {
      resetRecording("GSR/PPG timing drift exceeded buffer; recording reset.");
      return;
    }
    // n samples have now been emitted; next instant is n * 19531.25 us.
    next_gsr_us += kGsrPeriodUs + (gsr_produced % 4 == 0 ? 1 : 0);
    drainPairs();
  }
}

void startRecording(float ir, const sehat_gyro::Axes& gyro) {
  gsr.reset();
  ppg.reset();
  gsr_produced = ppg_produced = paired = raw_index = 0;
  previous_ir = ir;
  previous_gyro = gyro;
  last_ppg_ms = millis();
  next_gsr_us = micros() + kGsrPeriodUs;
  active = true;
  queueGsr(readGsrUs());
  queuePpg(ir, sehat_gyro::magnitude(gyro));
  drainPairs();
  Serial.println("Recording: 51.2 Hz aligned samples; 30 s windows, 50% overlap.");
}

// MAX30102 delivers 50 Hz. Convert IR and gyro to the shared 51.2-Hz index
// by linear interpolation; 50/51.2 = 125/128 exactly.
void addSensorSample(float ir, const sehat_gyro::Axes& gyro) {
  if (!active) {
    startRecording(ir, gyro);
    return;
  }
  ++raw_index;
  last_ppg_ms = millis();
  while (active && ppg_produced * 125ULL <= raw_index * 128ULL) {
    const double fraction = static_cast<double>(
        ppg_produced * 125ULL - (raw_index - 1ULL) * 128ULL) / 128.0;
    const float aligned_ir = std::isfinite(ir) && std::isfinite(previous_ir)
        ? previous_ir + static_cast<float>(fraction * (ir - previous_ir)) : NAN;
    const sehat_gyro::Axes axes = {
        previous_gyro.x + static_cast<float>(fraction * (gyro.x - previous_gyro.x)),
        previous_gyro.y + static_cast<float>(fraction * (gyro.y - previous_gyro.y)),
        previous_gyro.z + static_cast<float>(fraction * (gyro.z - previous_gyro.z))
    };
    if (!queuePpg(aligned_ir, sehat_gyro::magnitude(axes))) {
      resetRecording("PPG/GSR timing drift exceeded buffer; recording reset.");
      return;
    }
    drainPairs();
  }
  previous_ir = ir;
  previous_gyro = gyro;
}

void flushRecording() {
  if (!active) return;
  drainPairs();
  sehat_gsr::Features g;
  sehat_ppg::Features p;
  const bool g_ready = gsr.flush(g);
  const bool p_ready = ppg.flush(p);
  if (g_ready && p_ready && g.window_samples == p.window_samples)
    reportWindow(g, p);
  resetRecording("Recording closed.");
}

void calibrateWithoutFingers() {
  resetRecording("Calibrating Grove GSR without fingers...");
  float sum = 0.0f;
  for (uint8_t i = 0; i < 32; ++i) {
    sum += readGroveAdc10();
    delay(5);  // Acquisition is paused for deliberate calibration only.
  }
  calibration_adc10 = sum / 32.0f;
  Serial.printf("GSR calibration ADC10=%.2f. Attach electrodes.\n",
                calibration_adc10);
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(kGsrPin, ADC_11db);
  Wire.begin(kSdaPin, kSclPin);
  Wire.setClock(100000);
  if (!max30102.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("MAX30102 not detected.");
    while (true) delay(1000);
  }
  max30102.setup(0x1F, 1, 2, kSensorHz, 411, 4096);
  max30102.disableFIFORollover();
  Serial.println(sehat_gyro::begin() ? "MPU-9250 ready." :
                 "MPU-9250 unavailable; using low-motion PPG filter.");
  Serial.println("Remove GSR electrodes and send 'c' to calibrate.");
  Serial.println("Attach electrodes/finger and send 's' to start; 'f' flushes, 'r' resets.");
  Serial.println("Model output: predicted fasting duration in hours (S1 only).");
}

void loop() {
  while (Serial.available()) {
    const char command = static_cast<char>(Serial.read());
    if (command == 'c' || command == 'C') calibrateWithoutFingers();
    else if (command == 's' || command == 'S') {
      if (std::isfinite(calibration_adc10)) {
        resetRecording("Starting a new calibrated recording.");
        acquisition_enabled = true;
      } else Serial.println("Calibrate GSR with 'c' before starting.");
    }
    else if (command == 'f' || command == 'F') flushRecording();
    else if (command == 'r' || command == 'R')
      resetRecording("Recording reset; GSR calibration retained.");
  }
  if (!std::isfinite(calibration_adc10) || !acquisition_enabled) return;

  if (active) sampleGsrDue();
  if (active && millis() - last_ppg_ms > 250) {
    resetRecording("PPG sample timeout; recording reset.");
    return;
  }
  const uint16_t received = max30102.check();
  if (received >= 32) {
    resetRecording("MAX30102 FIFO overflow risk; recording reset.");
    return;
  }
  while (max30102.available()) {
    if (active) sampleGsrDue();
    const uint32_t ir = max30102.getFIFOIR();
    max30102.nextSample();
    addSensorSample(ir == 0 || ir >= 0x3FFFF ? NAN : static_cast<float>(ir),
                    sehat_gyro::read());
    if (active) sampleGsrDue();
  }
}
