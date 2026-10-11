// SEHAT: pembacaan Grove GSR dan preprocessing fitur GSR pada ESP32.
// Buka file ini langsung di Arduino IDE; gsr_preprocessing_esp32.h harus
// berada di folder sketch yang sama. Pilih board ESP32 yang dipakai.
//
// Pipeline: konduktansi terkalibrasi (uS) -> interpolasi sampel hilang ->
// Butterworth low-pass orde 2, 1 Hz, filtfilt -> mean, varians, entropi.
// Parameter window: 51.2 Hz, 30 detik, overlap 50%, seperti notebook.

#include <Arduino.h>
#include "gsr_preprocessing_esp32.h"

// Grove GSR: SIG -> pin analog ini, VCC -> 3V3, GND -> GND.
// Ubah A0 bila jalur analog board Anda memakai pin lain.
constexpr uint8_t GSR_PIN = 34;

static sehat_gsr::Processor gsr_processor;  // alokasikan global (~18,5 KB)
static float calibration_adc10 = NAN;
static uint32_t next_sample_us = 0;
static uint32_t sample_index = 0;
static uint32_t last_status_ms = 0;

// Dokumentasi Grove menggunakan pembacaan ADC 10-bit (0..1023). ESP32 dibaca
// dengan resolusi 12-bit lalu dipetakan ke skala yang dipakai rumus Grove.
float readGroveAdc10() {
  const int adc12 = analogRead(GSR_PIN);
  return static_cast<float>(adc12) * (1023.0f / 4095.0f);
}

// Rumus resistansi Grove GSR dari Seeed, kemudian R (ohm) -> G (uS).
// Sensor ini harus dikalibrasi dahulu tanpa jari. Hasil tidak valid jika
// pembacaan saat dipakai >= nilai kalibrasi (penyebut <= 0).
float groveConductanceUs(float adc10) {
  const float delta = calibration_adc10 - adc10;
  if (!std::isfinite(calibration_adc10) || delta <= 0.0f) return NAN;
  const float resistance_ohm =
      ((1024.0f + 2.0f * adc10) * 10000.0f) / delta;
  if (!std::isfinite(resistance_ohm) || resistance_ohm <= 0.0f) return NAN;
  return 1000000.0f / resistance_ohm;
}

void calibrateWithoutFingers() {
  // Lepas kedua elektroda dari jari dan atur potensiometer hingga nilai
  // ADC minimal/stabil sebelum mengirim huruf c lewat Serial Monitor.
  float sum = 0.0f;
  constexpr int kCalibrationReads = 32;
  for (int i = 0; i < kCalibrationReads; ++i) {
    sum += readGroveAdc10();
    delay(5);
  }
  calibration_adc10 = sum / kCalibrationReads;
  gsr_processor.reset();
  sample_index = 0;
  next_sample_us = micros();
  Serial.printf("Kalibrasi ADC10 = %.2f. Pasang elektroda pada jari.\n",
                calibration_adc10);
}

void printFeatures(const sehat_gsr::Features& features) {
  if (features.valid) {
    Serial.printf("gsr_mean=%.8f,gsr_var=%.8f,gsr_entropy=%.8f,"
                  "interpolated=%u,window_samples=%u\n",
                  features.gsr_mean, features.gsr_var, features.gsr_entropy,
                  static_cast<unsigned>(features.interpolated_samples),
                  static_cast<unsigned>(features.window_samples));
  } else {
    Serial.println("Window GSR tidak valid: semua sampel hilang.");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(GSR_PIN, INPUT);
  analogReadResolution(12);
  next_sample_us = micros();
  Serial.println("SEHAT GSR | 51.2 Hz | window 30 s, overlap 50%");
  Serial.println("1. Lepas elektroda dari jari; atur potensiometer sampai ADC minimum.");
  Serial.println("2. Kirim 'c' di Serial Monitor untuk menyimpan kalibrasi.");
  Serial.println("3. Pasang elektroda; fitur pertama muncul setelah 30 detik.");
  Serial.println("Kirim 'f' untuk mengeluarkan sisa window pada akhir rekaman.");
  Serial.println("Kirim 'r' untuk menghapus kalibrasi dan mengulang.");
}

void loop() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());
    if (command == 'c' || command == 'C') calibrateWithoutFingers();
    if (command == 'f' || command == 'F') {
      sehat_gsr::Features tail;
      if (gsr_processor.flush(tail)) printFeatures(tail);
      sample_index = 0;
      next_sample_us = micros();
    }
    if (command == 'r' || command == 'R') {
      calibration_adc10 = NAN;
      gsr_processor.reset();
      Serial.println("Kalibrasi dihapus. Lepas elektroda lalu kirim 'c'.");
    }
  }

  if (!std::isfinite(calibration_adc10)) {
    if (millis() - last_status_ms >= 1000) {
      last_status_ms = millis();
      Serial.printf("ADC10 tanpa jari: %.2f | menunggu 'c'\n", readGroveAdc10());
    }
    return;
  }

  const int32_t late_us = static_cast<int32_t>(micros() - next_sample_us);
  if (late_us < 0) return;
  if (late_us > 39062) {  // lebih dari dua periode: window tidak lagi kontinu
    gsr_processor.reset();
    sample_index = 0;
    next_sample_us = micros();
    Serial.println("Jeda sampling terdeteksi; window GSR diulang.");
    return;
  }

  const float adc10 = readGroveAdc10();
  const float conductance_us = groveConductanceUs(adc10);
  sehat_gsr::Features features;
  if (gsr_processor.addSample(conductance_us, features)) printFeatures(features);

  if (millis() - last_status_ms >= 1000) {
    last_status_ms = millis();
    Serial.printf("ADC10=%.2f, GSR_us=%.6f\n", adc10, conductance_us);
  }

  // 51,2 Hz persis: empat interval adalah 19531+19531+19531+19532 us.
  ++sample_index;
  next_sample_us += 19531u + (sample_index % 4u == 0u ? 1u : 0u);
}
