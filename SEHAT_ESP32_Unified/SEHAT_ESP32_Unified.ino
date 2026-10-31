/*
  ========================================================================================
  SEHAT: Smart Electronic-based Hydration Analysis & Tracking
  Unified On-Device Firmware: Sensor Acquisition + DSP + TinyML + Wi-Fi Telemetry Ingestion
  ========================================================================================

  Hardware Stack:
  - Microcontroller: ESP32 (DevKit v1 or Seeed Studio XIAO ESP32-C3 / S3)
  - Photoplethysmography (PPG) & SpO2: MAX30102 (I2C address: 0x57)
  - Motion / Inertial Unit: GY-9250 / MPU-9250 (I2C address: 0x68 / 0x69)
  - Galvanic Skin Response (GSR): Grove GSR Sensor (Analog ADC Pin)

  Required Arduino Libraries (Install via Library Manager):
  - "SparkFun MAX3010x Pulse and Proximity Sensor Library" by SparkFun
  - "ArduinoJson" (v6 or v7) by Benoit Blanchon
*/

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <MAX30105.h>
#include <spo2_algorithm.h>

// Type definition required by emlearn C Header
typedef float float32;

// Set to 1 to enable local on-device Random Forest inference,
// or 0 to focus on preprocessing & feature extraction telemetry streaming.
#define ENABLE_EMBEDDED_ML 0

// SEHAT DSP & TinyML Modules
#include "ppg_preprocessing_esp32.h"
#include "gsr_preprocessing_esp32.h"
#if ENABLE_EMBEDDED_ML
#include "rf_hydration_model.h"
#endif

// ========================================================================================
// 1. CONFIGURATION: Wi-Fi, Server & Pinout
// ========================================================================================

// Set to 1 if you want the ESP32 to send HTTP POST directly over Wi-Fi without USB bridge.
// Set to 0 if connected via USB Serial cable using serial_bridge.py (Recommended).
#define ENABLE_WIFI 0

// --- Wi-Fi & Backend Endpoint ---
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// Adjust to your computer's local IP address (e.g. 192.168.1.100) running the SEHAT server
const char* SERVER_URL = "http://192.168.1.100:5000/api/measurements";

// --- Pin Definitions ---
#if defined(ARDUINO_SEEED_XIAO_ESP32C3) || defined(ARDUINO_XIAO_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C3) || defined(ARDUINO_SEEED_XIAO_ESP32S3) || defined(ARDUINO_XIAO_ESP32S3)
  constexpr int I2C_SDA_PIN = D4;
  constexpr int I2C_SCL_PIN = D5;
  constexpr int GSR_ADC_PIN = A0;
#else
  // Default for ESP32 DevKit V1
  constexpr int I2C_SDA_PIN = 21;
  constexpr int I2C_SCL_PIN = 22;
  constexpr int GSR_ADC_PIN = 34; // Input-only ADC1 pin
#endif

// ========================================================================================
// 2. SENSOR & DSP GLOBAL INSTANCES
// ========================================================================================

static MAX30105 max30102;

static sehat_ppg::Processor ppg_processor;
static sehat_gsr::Processor gsr_processor;

// MPU-9250 Gyro Configuration
static uint8_t gyro_i2c_addr = 0; // 0x68 or 0x69
struct GyroData { float x, y, z; };
static GyroData prev_gyro = {NAN, NAN, NAN};
static float prev_ir = NAN;
static bool have_prev_sample = false;

// GSR Calibration state
static float gsr_baseline_adc10 = 500.0f; // Default fallback if uncalibrated
static bool gsr_is_calibrated = false;

// 51.2 Hz Sampling Scheduler
static uint32_t next_sample_micros = 0;
static uint32_t sample_cycle_count = 0;
static uint32_t last_telemetry_post_ms = 0;
static uint32_t last_debug_print_ms = 0;

// Shared latest readings
static float latest_bpm = 72.0f;
static float latest_gsr_us = 9.5f;
static float latest_predicted_hours = 0.0f;
static bool has_max30102 = false;
static uint32_t spo2_ir[100];
static uint32_t spo2_red[100];
static size_t spo2_count = 0;
static float latest_spo2 = NAN;
static bool spo2_valid = false;

// Real-time instantaneous PPG beat detector for live dashboard streaming
static float live_bpm = 0.0f;
static float ppg_prev_filtered = 0.0f;
static bool ppg_rising = false;
static uint32_t last_peak_time_ms = 0;

void trackLiveHeartbeat(float ir_val) {
  uint32_t now_ms = millis();
  if (ir_val < 30000.0f) {
    live_bpm = 0.0f;
    return;
  }
  // Drop live BPM back to 0 if no pulse peak has arrived in > 2.5 seconds
  if (last_peak_time_ms > 0 && (now_ms - last_peak_time_ms > 2500)) {
    live_bpm = 0.0f;
  }

  static float dc_estimate = 100000.0f;
  dc_estimate = 0.95f * dc_estimate + 0.05f * ir_val;
  float ac_val = ir_val - dc_estimate;

  static float ac_smoothed = 0.0f;
  ac_smoothed = 0.7f * ac_smoothed + 0.3f * ac_val;

  if (ac_smoothed > ppg_prev_filtered && !ppg_rising) {
    ppg_rising = true;
  } else if (ac_smoothed < ppg_prev_filtered && ppg_rising) {
    ppg_rising = false;
    if (ppg_prev_filtered > 20.0f) {
      uint32_t interval = now_ms - last_peak_time_ms;
      if (interval >= 300 && interval <= 1800) { // 33 to 200 BPM
        float instant_bpm = 60000.0f / static_cast<float>(interval);
        if (live_bpm <= 0.0f) live_bpm = instant_bpm;
        else live_bpm = 0.7f * live_bpm + 0.3f * instant_bpm;
      }
      last_peak_time_ms = now_ms;
    }
  }
  ppg_prev_filtered = ac_smoothed;
}

void addSpo2Sample(uint32_t ir, uint32_t red) {
  // The Maxim algorithm expects 100 samples at 25 Hz. The FIFO runs at 50 Hz.
  static uint8_t decimation = 0;
  if (++decimation < 2) return;
  decimation = 0;
  if (ir < 30000 || red < 30000) {
    spo2_count = 0;
    spo2_valid = false;
    latest_spo2 = NAN;
    return;
  }
  spo2_ir[spo2_count] = ir;
  spo2_red[spo2_count++] = red;
  if (spo2_count < 100) return;

  int32_t value = -999;
  int32_t algorithm_hr = -999;
  int8_t valid = 0;
  int8_t hr_valid = 0;
  maxim_heart_rate_and_oxygen_saturation(spo2_ir, 100, spo2_red,
                                        &value, &valid, &algorithm_hr, &hr_valid);
  spo2_valid = valid == 1 && value >= 0 && value <= 100;
  latest_spo2 = spo2_valid ? static_cast<float>(value) : NAN;
  memmove(spo2_ir, spo2_ir + 25, 75 * sizeof(uint32_t));
  memmove(spo2_red, spo2_red + 25, 75 * sizeof(uint32_t));
  spo2_count = 75;
}

// ========================================================================================
// 3. MPU-9250 GYROSCOPE HELPER FUNCTIONS
// ========================================================================================

bool writeMPURegister(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return (Wire.endTransmission() == 0);
}

bool readMPURegister(uint8_t addr, uint8_t reg, uint8_t& val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)1) != 1) return false;
  val = Wire.read();
  return true;
}

bool initMPU9250() {
  const uint8_t addrs[2] = {0x68, 0x69};
  uint8_t whoami = 0;

  for (uint8_t a : addrs) {
    if (readMPURegister(a, 0x75, whoami)) {
      if (whoami == 0x71 || whoami == 0x73 || whoami == 0x68) {
        gyro_i2c_addr = a;
        break;
      }
    }
  }

  if (!gyro_i2c_addr) {
    Serial.println("[MPU9250] No gyro found. Using fallback low-motion filter branch.");
    return false;
  }

  // Wake device and set ±500 dps
  writeMPURegister(gyro_i2c_addr, 0x6B, 0x80); // Reset
  delay(50);
  writeMPURegister(gyro_i2c_addr, 0x6B, 0x01); // Auto clock
  writeMPURegister(gyro_i2c_addr, 0x1A, 0x03); // DLPF ~41Hz
  writeMPURegister(gyro_i2c_addr, 0x19, 0x09); // 100Hz ODR
  writeMPURegister(gyro_i2c_addr, 0x1B, 0x08); // FS_SEL=1 (+/-500 dps, 65.5 LSB/(deg/s))

  Serial.printf("[MPU9250] Active on 0x%02X (WHO_AM_I=0x%02X)\n", gyro_i2c_addr, whoami);
  return true;
}

GyroData readGyroscope() {
  if (!gyro_i2c_addr) return {NAN, NAN, NAN};
  Wire.beginTransmission(gyro_i2c_addr);
  Wire.write(0x43); // GYRO_XOUT_H
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(gyro_i2c_addr, (uint8_t)6) != 6) {
    return {NAN, NAN, NAN};
  }

  int16_t gx = (Wire.read() << 8) | Wire.read();
  int16_t gy = (Wire.read() << 8) | Wire.read();
  int16_t gz = (Wire.read() << 8) | Wire.read();

  return { gx / 65.5f, gy / 65.5f, gz / 65.5f };
}

// ========================================================================================
// 4. GROVE GSR HELPER FUNCTIONS
// ========================================================================================

float readGSRAdc10() {
  int adc12 = analogRead(GSR_ADC_PIN);
  return static_cast<float>(adc12) * (1023.0f / 4095.0f);
}

float calculateGSRConductanceUs(float adc10) {
  float delta = gsr_baseline_adc10 - adc10;
  if (!std::isfinite(gsr_baseline_adc10) || delta <= 0.0f) return NAN;
  float resistance_ohm = ((1024.0f + 2.0f * adc10) * 10000.0f) / delta;
  if (!std::isfinite(resistance_ohm) || resistance_ohm <= 0.0f) return NAN;
  return 1000000.0f / resistance_ohm;
}

void performGSRCalibration() {
  Serial.println("\n[GSR] Calibrating without finger contact... Please wait.");
  float sum = 0.0f;
  for (int i = 0; i < 32; i++) {
    sum += readGSRAdc10();
    delay(10);
  }
  gsr_baseline_adc10 = sum / 32.0f;
  gsr_is_calibrated = true;
  gsr_processor.reset();
  Serial.printf("[GSR] Calibration complete. Baseline ADC10 = %.2f\n\n", gsr_baseline_adc10);
}

// ========================================================================================
// 5. WI-FI & HTTP TELEMETRY INGESTION
// ========================================================================================

void connectToWiFi() {
#if ENABLE_WIFI
  if (strcmp(WIFI_SSID, "YOUR_WIFI_SSID") == 0) return;
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[Wi-Fi] Connecting to '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start_ms = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start_ms < 6000) {
    delay(300);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[Wi-Fi] Connected! Local IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[Wi-Fi] Connection timed out. Operating in offline logging mode.");
  }
#endif
}

void transmitMeasurementToBackend(float bpm, float gsr, float predicted_hours) {
#if ENABLE_WIFI
  if (strcmp(WIFI_SSID, "YOUR_WIFI_SSID") == 0) return;
  if (WiFi.status() != WL_CONNECTED) return; // Non-blocking: never freeze the DSP loop

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Create JSON Payload
  StaticJsonDocument<384> doc;
  doc["bpm"] = bpm;
  if (spo2_valid) doc["spo2"] = latest_spo2;
  else doc["spo2"] = nullptr;
  doc["spo2Valid"] = spo2_valid;
  doc["gsr"] = gsr;
  doc["predictedHoursSinceHydration"] = predicted_hours;
  doc["notes"] = "ESP32 TinyML RF Inference";

  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  if (httpCode > 0) {
    Serial.printf("[HTTP POST] Status %d | Payload synced to SEHAT SQLite DB.\n", httpCode);
  } else {
    Serial.printf("[HTTP ERROR] Failed to send measurement: %s\n", http.errorToString(httpCode).c_str());
  }
  http.end();
#endif
}

// ========================================================================================
// 6. SETUP
// ========================================================================================

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2500);

  Serial.println("\n=======================================================");
  Serial.println("  SEHAT: Smart Electronic Hydration Analysis & Tracking");
  Serial.println("  Unified ESP32 Biosignal Intelligence Firmware");
  Serial.println("=======================================================\n");

  pinMode(GSR_ADC_PIN, INPUT);
  analogReadResolution(12);

  // 1. Initialize I2C
  Serial.printf("[I2C] Initializing on SDA:%d, SCL:%d... ", I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Serial.println("OK");

  // 2. Initialize MAX30102
  Serial.print("[MAX30102] Probing sensor... ");
  if (!max30102.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("NOT FOUND! Check wiring (3.3V, GND, SDA, SCL).");
  } else {
    has_max30102 = true;
    Serial.println("FOUND!");
    // 200 samples/s averaged by 4 = 50 paired red/IR FIFO samples/s.
    max30102.setup(0x1F, 4, 2, 200, 411, 4096);
    max30102.enableDIETEMPRDY();
  }

  // 3. Initialize MPU-9250 Gyro
  initMPU9250();

  // 4. Connect to Wi-Fi
  connectToWiFi();

  // 5. Initial Quick GSR Calibration
  performGSRCalibration();

  Serial.println("\n[SEHAT Pipeline Ready] Sampling at 51.2 Hz (30s window, 50% overlap).");
  Serial.println("Commands: 'c' = Re-calibrate GSR | 'f' = Flush window\n");

  next_sample_micros = micros();
}

// ========================================================================================
// 7. MAIN SAMPLING & DSP INFERENCE LOOP
// ========================================================================================

void loop() {
  // Process User Commands from Serial
  if (Serial.available()) {
    char cmd = Serial.read();
    if (cmd == 'c' || cmd == 'C') {
      performGSRCalibration();
    } else if (cmd == 'f' || cmd == 'F') {
      sehat_gsr::Features dummy_g;
      sehat_ppg::Features dummy_p;
      gsr_processor.flush(dummy_g);
      ppg_processor.flush(dummy_p);
      Serial.println("[DSP] Flushed partial windows.");
    }
  }

  // Precise 51.2 Hz Periodic Tick (~19,531 µs)
  int32_t time_diff = micros() - next_sample_micros;
  if (time_diff < 0) return;

  // Add 1 µs every 4th sample to maintain exact 19,531.25 µs cadence
  uint32_t step_us = (sample_cycle_count % 4 == 0) ? 19532 : 19531;
  next_sample_micros += step_us;
  sample_cycle_count++;

  // 1. Acquire Paired Sensor Readings
  uint32_t raw_ir = 0;
  uint32_t raw_red = 0;
  if (has_max30102) {
    max30102.check();
    while (max30102.available()) {
      raw_ir = max30102.getFIFOIR();
      raw_red = max30102.getFIFORed();
      max30102.nextSample();
      addSpo2Sample(raw_ir, raw_red);
      if (raw_ir > 30000) {
        trackLiveHeartbeat(static_cast<float>(raw_ir));
      }
    }
  }
  if (raw_ir <= 30000) {
    trackLiveHeartbeat(0.0f);
  }
  float current_ir = (raw_ir > 30000) ? static_cast<float>(raw_ir) : NAN;
  GyroData current_gyro = readGyroscope();
  float current_gsr_adc = readGSRAdc10();
  float current_gsr_us = calculateGSRConductanceUs(current_gsr_adc);

  // Update live vital state
  if (std::isfinite(current_gsr_us)) latest_gsr_us = current_gsr_us;

  // 2. Feed GSR Preprocessing Engine
  sehat_gsr::Features gsr_feats;
  bool gsr_window_ready = gsr_processor.addSample(current_gsr_us, gsr_feats);

  // 3. Feed PPG Preprocessing Engine (with 50->51.2 Hz Linear Interpolation)
  sehat_ppg::Features ppg_feats;
  bool ppg_window_ready = false;

  if (have_prev_sample) {
    // Intermediate sample for 51.2 Hz matching
    float interp_ir = (std::isfinite(current_ir) && std::isfinite(prev_ir)) ? 0.5f * (prev_ir + current_ir) : current_ir;
    float interp_gx = (std::isfinite(current_gyro.x) && std::isfinite(prev_gyro.x)) ? 0.5f * (prev_gyro.x + current_gyro.x) : current_gyro.x;
    float interp_gy = (std::isfinite(current_gyro.y) && std::isfinite(prev_gyro.y)) ? 0.5f * (prev_gyro.y + current_gyro.y) : current_gyro.y;
    float interp_gz = (std::isfinite(current_gyro.z) && std::isfinite(prev_gyro.z)) ? 0.5f * (prev_gyro.z + current_gyro.z) : current_gyro.z;

    float gyro_mag = (std::isfinite(interp_gx) && std::isfinite(interp_gy) && std::isfinite(interp_gz))
                      ? std::sqrt(interp_gx * interp_gx + interp_gy * interp_gy + interp_gz * interp_gz)
                      : NAN;

    ppg_window_ready = ppg_processor.addSample(interp_ir, gyro_mag, ppg_feats);
  }

  prev_ir = current_ir;
  prev_gyro = current_gyro;
  have_prev_sample = true;

  if (ppg_window_ready && ppg_feats.ppg_available && std::isfinite(ppg_feats.mean_hr)) {
    latest_bpm = ppg_feats.mean_hr;
  }

  // 4. Feature Extraction & Telemetry Dispatch (When 30s Window is Ready)
  if (ppg_window_ready || gsr_window_ready) {
    Serial.println("\n----------------- [30s WINDOW READY: FEATURE DISPATCH] -----------------");

    float feat_gsr_mean = gsr_feats.valid ? static_cast<float>(gsr_feats.gsr_mean) : latest_gsr_us;
    float feat_gsr_var = gsr_feats.valid ? static_cast<float>(gsr_feats.gsr_var) : 0.05f;
    float feat_gsr_entropy = gsr_feats.valid ? static_cast<float>(gsr_feats.gsr_entropy) : 1.2f;
    float feat_bpm = (ppg_feats.ppg_available && std::isfinite(ppg_feats.mean_hr)) ? static_cast<float>(ppg_feats.mean_hr) : latest_bpm;
    float feat_rmssd = (ppg_feats.ppg_available && std::isfinite(ppg_feats.rmssd)) ? static_cast<float>(ppg_feats.rmssd) : 32.0f;
    float feat_sdnn = (ppg_feats.ppg_available && std::isfinite(ppg_feats.sdnn)) ? static_cast<float>(ppg_feats.sdnn) : 40.0f;
    float feat_pnn50 = (ppg_feats.ppg_available && std::isfinite(ppg_feats.pnn50)) ? static_cast<float>(ppg_feats.pnn50) : 12.0f;
    float feat_n_peaks = ppg_feats.ppg_available ? static_cast<float>(ppg_feats.n_peaks) : 36.0f;

    Serial.printf(">> PPG Features: HR=%.1f BPM, RMSSD=%.1f ms, SDNN=%.1f ms, pNN50=%.1f %%\n",
                  feat_bpm, feat_rmssd, feat_sdnn, feat_pnn50);
    if (spo2_valid) Serial.printf(">> SpO2: %.0f %% | valid=1\n", latest_spo2);
    else Serial.println(">> SpO2: null | valid=0");
    Serial.printf(">> GSR Features: Mean=%.2f uS, Var=%.4f, Entropy=%.2f\n",
                  feat_gsr_mean, feat_gsr_var, feat_gsr_entropy);

#if ENABLE_EMBEDDED_ML
    // Assemble 9-dimensional Feature Vector for TinyML Random Forest
    float32 ml_features[9] = {
      feat_gsr_mean, feat_gsr_var, feat_gsr_entropy,
      feat_bpm, feat_rmssd, feat_sdnn, feat_pnn50, feat_n_peaks,
      ppg_feats.ppg_available ? 1.0f : 0.0f
    };
    latest_predicted_hours = hydration_rf_predict(ml_features, 9);
    latest_predicted_hours = constrain(latest_predicted_hours, 0.2f, 24.0f);
    Serial.printf(">> On-Device TinyML Output: %.2f hours since hydration (%s)\n",
                  latest_predicted_hours, latest_predicted_hours > 10.0f ? "AT_RISK" : "WELL_HYDRATED");
#else
    // Backend server will calculate hydration estimate or store raw preprocessed telemetry
    latest_predicted_hours = 0.0f;
#endif

    // 5. Ingest to Backend SQLite Database via Wi-Fi HTTP POST
    transmitMeasurementToBackend(
      feat_bpm,
      feat_gsr_mean,
      latest_predicted_hours
    );
    Serial.println("--------------------------------------------------------------------\n");
  }

  // --- Status Log (every 250ms for real-time dashboard gauges) ---
  if (millis() - last_debug_print_ms >= 250) {
    last_debug_print_ms = millis();
    float disp_bpm = (live_bpm >= 35.0f && live_bpm <= 220.0f) ? live_bpm : 0.0f;
    if (spo2_valid) {
      Serial.printf("[Live Stream] IR: %u | BPM: %.1f | SpO2: %.0f %% | valid=1 | GSR: %.2f uS\n",
                    raw_ir, disp_bpm, latest_spo2, latest_gsr_us);
    } else {
      Serial.printf("[Live Stream] IR: %u | BPM: %.1f | SpO2: null | valid=0 | GSR: %.2f uS\n",
                    raw_ir, disp_bpm, latest_gsr_us);
    }
  }
}
