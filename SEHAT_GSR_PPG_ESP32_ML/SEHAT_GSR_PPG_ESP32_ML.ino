/*
 * SEHAT - Estimasi hidrasi dari PPG (MAX30102) + GSR di ESP32
 * Model: ExtraTrees (emlearn) -> et_hydration_model_S1.h (taruh satu folder dengan .ino ini)
 *
 * Alur: sampel PPG (50 Hz) + GSR (10 Hz) -> window 30 detik -> 9 fitur
 *       -> standardisasi (z-score) -> hydration_et_predict()
 */
#include <Wire.h>
#include <MAX30105.h>

typedef float float32;                 // header emlearn memakai tipe float32
#include "et_hydration_model_S1.h"     // di-include SEKALI saja (ada definisi fungsi di dalamnya)

// =====================================================================
// KONFIGURASI
// =====================================================================
// --- Pin ---
constexpr uint8_t PIN_SDA = 21;
constexpr uint8_t PIN_SCL = 22;
constexpr uint8_t PIN_GSR = 34;        // ADC1 (aman dipakai bersamaan dengan WiFi)

// --- PPG ---
constexpr uint16_t PPG_FS         = 50;                 // Hz, harus sama dengan sensor.setup()
constexpr float    PPG_DT_MS      = 1000.0f / PPG_FS;
constexpr uint32_t FINGER_IR_MIN  = 20000;              // IR di bawah ini = jari tidak menempel
constexpr uint8_t  SETTLE_SEC     = 3;                  // waktu stabilisasi sebelum window mulai
constexpr float    DC_ALPHA       = 0.01f;              // IIR baseline (tau ~2 s)
constexpr float    LP_ALPHA       = 0.30f;              // IIR low-pass (~3 Hz)
constexpr float    PEAK_THR_FRAC  = 0.5f;               // ambang peak = 50% envelope amplitudo
constexpr float    PEAK_THR_MIN   = 20.0f;              // ambang minimum (ADC count)
constexpr float    IBI_MIN_MS     = 300.0f;             // 200 bpm
constexpr float    IBI_MAX_MS     = 1500.0f;            // 40 bpm
constexpr float    REFRACTORY_FRAC = 0.65f;             // gap minimum antar peak = 65% IBI referensi
constexpr float    IBI_OUTLIER    = 0.25f;              // buang IBI yang menyimpang >25% dari median

// --- GSR ---
constexpr uint16_t GSR_FS         = 10;                 // Hz
constexpr uint16_t GSR_DT_MS      = 1000 / GSR_FS;
constexpr float    GSR_R_REF      = 100000.0f;          // ohm, resistor referensi di rangkaian (SESUAIKAN)
constexpr float    GSR_TONIC_TAU  = 4.0f;               // detik, untuk memisahkan komponen fasik
constexpr float    SCR_THRESHOLD  = 0.05f;              // uS, amplitudo minimum 1 SCR

// --- Window & model ---
constexpr uint32_t WINDOW_SEC     = 30;
constexpr uint16_t MIN_BEATS      = 15;                 // minimal beat valid per window
constexpr uint16_t MAX_IBI        = 128;
constexpr uint16_t GSR_BUF_N      = WINDOW_SEC * GSR_FS;

// Urutan fitur HARUS sama persis dengan urutan saat training.
// Jika berbeda, cukup ubah urutan enum ini.
enum Feature : uint8_t {
  F_GSR_MEAN,    // 0  rata-rata konduktansi (uS)
  F_GSR_STD,     // 1  simpangan baku GSR (uS)
  F_GSR_SLOPE,   // 2  kemiringan GSR (uS/detik)
  F_SCR_COUNT,   // 3  jumlah respons SCR per window
  F_HR_MEAN,     // 4  heart rate rata-rata (bpm)
  F_SDNN,        // 5  SDNN (ms)
  F_RMSSD,       // 6  RMSSD (ms)
  F_PI,          // 7  perfusion index (%)
  F_PNN50,       // 8  pNN50 (%)
  F_COUNT        // = 9, sesuai fitur terbesar yang dipakai model (features[8])
};

// Parameter StandardScaler dari training (scaler.mean_ dan scaler.scale_).
// Isi sesuai urutan enum di atas, lalu ubah SCALER_READY menjadi true.
constexpr bool  SCALER_READY = false;
const float SCALER_MEAN[F_COUNT] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
const float SCALER_STD [F_COUNT] = {1, 1, 1, 1, 1, 1, 1, 1, 1};

// =====================================================================
// STATE
// =====================================================================
MAX30105 sensor;

// --- PPG ---
float    dcLevel, acLp, yPrev1, yPrev2, envPeak, cycMin;
uint32_t ppgIdx;                        // indeks sampel di dalam window
float    lastPeakT, refIbi;                 // refIbi: IBI referensi (EMA) untuk refractory adaptif
bool     havePeak;
float    ibiBuf[MAX_IBI];
uint16_t nIbi;
float    piSum;
uint16_t settleLeft, lostCnt;
bool     fingerOn, windowActive;

// --- GSR ---
float    gsrBuf[GSR_BUF_N];
uint16_t gsrN, gsrBad;
uint32_t nextGsrMs;
float    lastGsr;

// --- Window ---
uint32_t windowStartMs, windowCount, lastStatusMs;

// =====================================================================
// GSR
// =====================================================================
// Pembacaan ADC -> konduktansi (uS), asumsi: kulit seri dengan GSR_R_REF, output di node ADC.
// Jika rumus saat training berbeda (mis. nilai ADC mentah / modul Grove), ganti fungsi ini.
float readGsrMicroSiemens(bool &ok) {
  uint32_t acc = 0;
  for (uint8_t i = 0; i < 16; i++) acc += analogRead(PIN_GSR);   // oversampling 16x
  float adc = acc / 16.0f;
  ok = (adc > 20.0f && adc < 4075.0f);                            // di luar rentang = tidak valid
  adc = constrain(adc, 1.0f, 4094.0f);
  return 1e6f * adc / (GSR_R_REF * (4095.0f - adc));
}

void sampleGsr() {
  if (!windowActive || gsrN >= GSR_BUF_N || (int32_t)(millis() - nextGsrMs) < 0) return;
  bool ok;
  lastGsr = readGsrMicroSiemens(ok);
  if (!ok) gsrBad++;
  gsrBuf[gsrN++] = lastGsr;
  nextGsrMs += GSR_DT_MS;
}

bool computeGsrFeatures(float *f) {
  if (gsrN < GSR_BUF_N * 8 / 10 || gsrBad > gsrN / 5) return false;   // data kurang / kontak buruk

  // Mean & std
  double sum = 0;
  for (uint16_t i = 0; i < gsrN; i++) sum += gsrBuf[i];
  double mean = sum / gsrN, var = 0;
  for (uint16_t i = 0; i < gsrN; i++) var += sq(gsrBuf[i] - mean);
  f[F_GSR_MEAN] = mean;
  f[F_GSR_STD]  = sqrt(var / gsrN);

  // Slope (regresi linear terhadap waktu dalam detik)
  double tMean = (gsrN - 1) * 0.5 / GSR_FS, num = 0, den = 0;
  for (uint16_t i = 0; i < gsrN; i++) {
    double dt = (double)i / GSR_FS - tMean;
    num += dt * (gsrBuf[i] - mean);
    den += dt * dt;
  }
  f[F_GSR_SLOPE] = (den > 0) ? num / den : 0;

  // Jumlah SCR: komponen fasik = sinyal - tonic (EMA lambat), hitung rising-edge melewati threshold
  float alpha = 1.0f - expf(-(1.0f / GSR_FS) / GSR_TONIC_TAU);
  float tonic = gsrBuf[0];
  bool armed = true;
  uint16_t scr = 0;
  for (uint16_t i = 0; i < gsrN; i++) {
    tonic += alpha * (gsrBuf[i] - tonic);
    float phasic = gsrBuf[i] - tonic;
    if (armed && phasic > SCR_THRESHOLD)          { scr++; armed = false; }
    else if (!armed && phasic < SCR_THRESHOLD * 0.5f) armed = true;   // hysteresis
  }
  f[F_SCR_COUNT] = scr;
  return true;
}

// =====================================================================
// PPG
// =====================================================================
void startWindow() {
  windowActive  = true;
  windowStartMs = millis();
  ppgIdx = 0; nIbi = 0; piSum = 0; havePeak = false;
  gsrN = 0; gsrBad = 0; nextGsrMs = windowStartMs;
}

void resetPpgState() {
  windowActive = false;
  acLp = yPrev1 = yPrev2 = envPeak = cycMin = 0;
  lostCnt = 0; refIbi = 0;
  ppgIdx = 0; nIbi = 0; piSum = 0; havePeak = false;
  gsrN = 0; gsrBad = 0;
}

void onPpgSample(uint32_t ir) {
  // Deteksi jari
  if (ir < FINGER_IR_MIN) {
    if (fingerOn && ++lostCnt > PPG_FS) {               // hilang > 1 detik
      fingerOn = false;
      resetPpgState();
      Serial.println("Jari terlepas, window direset.");
    }
    return;
  }
  lostCnt = 0;
  if (!fingerOn) {
    fingerOn = true;
    resetPpgState();
    dcLevel = ir;
    settleLeft = SETTLE_SEC * PPG_FS;
    Serial.println("Jari terdeteksi, menstabilkan sinyal...");
  }

  // Filter: buang DC (IIR lambat) lalu low-pass
  dcLevel += DC_ALPHA * (ir - dcLevel);
  acLp    += LP_ALPHA * ((ir - dcLevel) - acLp);
  float y0 = acLp;

  // Envelope amplitudo untuk ambang adaptif
  envPeak = (y0 > envPeak) ? y0 : envPeak * 0.9985f;

  // Fase stabilisasi: filter jalan, deteksi belum
  if (!windowActive) {
    yPrev2 = yPrev1; yPrev1 = y0;
    if (settleLeft > 0 && --settleLeft == 0) { startWindow(); cycMin = y0; }
    return;
  }

  uint32_t idx = ppgIdx++;
  if (y0 < cycMin) cycMin = y0;

  // Peak = yPrev1 adalah maksimum lokal dan di atas ambang
  bool isPeak = yPrev1 > yPrev2 && yPrev1 >= y0 &&
                yPrev1 > max(PEAK_THR_FRAC * envPeak, PEAK_THR_MIN);
  if (isPeak) {
    // Interpolasi parabola agar waktu peak lebih halus dari resolusi 20 ms
    float denom = yPrev2 - 2.0f * yPrev1 + y0;
    float off = (fabsf(denom) > 1e-6f) ? 0.5f * (yPrev2 - y0) / denom : 0.0f;
    float tPeak = ((float)idx - 1.0f + constrain(off, -0.5f, 0.5f)) * PPG_DT_MS;

    if (!havePeak) {
      lastPeakT = tPeak; havePeak = true; cycMin = y0;
    } else {
      float ibi = tPeak - lastPeakT;
      float minGap = max(IBI_MIN_MS, REFRACTORY_FRAC * refIbi);   // di bawah ini = peak palsu (mis. dicrotic notch)
      if (ibi >= minGap) {
        if (ibi <= IBI_MAX_MS && nIbi < MAX_IBI) {
          ibiBuf[nIbi++] = ibi;
          piSum += (yPrev1 - cycMin) / dcLevel * 100.0f; // amplitudo AC / DC
          refIbi = (refIbi == 0) ? ibi : 0.8f * refIbi + 0.2f * ibi;
        }
        lastPeakT = tPeak;                               // selalu resync walau IBI di luar rentang
        cycMin = y0;
      }
    }
  }
  yPrev2 = yPrev1; yPrev1 = y0;
}

// Median dari array (dicopy lalu insertion sort, n kecil)
float medianOf(const float *a, uint16_t n) {
  float t[MAX_IBI];
  for (uint16_t i = 0; i < n; i++) {
    float v = a[i]; int j = i - 1;
    while (j >= 0 && t[j] > v) { t[j + 1] = t[j]; j--; }
    t[j + 1] = v;
  }
  return (n & 1) ? t[n / 2] : 0.5f * (t[n / 2 - 1] + t[n / 2]);
}

bool computePpgFeatures(float *f) {
  if (nIbi < MIN_BEATS) return false;

  // Buang IBI outlier (artefak gerak / beat terlewat) terhadap median
  float med = medianOf(ibiBuf, nIbi);
  float clean[MAX_IBI]; bool adj[MAX_IBI];             // adj[i]: clean[i] bersebelahan langsung dengan clean[i-1]
  uint16_t m = 0; bool prevKept = false;
  for (uint16_t i = 0; i < nIbi; i++) {
    if (fabsf(ibiBuf[i] - med) <= IBI_OUTLIER * med) { clean[m] = ibiBuf[i]; adj[m++] = prevKept; prevKept = true; }
    else prevKept = false;
  }
  if (m < MIN_BEATS) return false;

  double sum = 0;
  for (uint16_t i = 0; i < m; i++) sum += clean[i];
  double mean = sum / m, var = 0;
  for (uint16_t i = 0; i < m; i++) var += sq(clean[i] - mean);

  // RMSSD & pNN50 hanya dari pasangan beat berurutan
  double sumSq = 0; uint16_t pairs = 0, nn50 = 0;
  for (uint16_t i = 1; i < m; i++) {
    if (!adj[i]) continue;
    float d = fabsf(clean[i] - clean[i - 1]);
    sumSq += d * d; pairs++;
    if (d > 50.0f) nn50++;
  }
  if (pairs == 0) return false;

  f[F_HR_MEAN] = 60000.0 / mean;
  f[F_SDNN]    = sqrt(var / (m - 1));
  f[F_RMSSD]   = sqrt(sumSq / pairs);
  f[F_PNN50]   = 100.0 * nn50 / pairs;
  f[F_PI]      = piSum / nIbi;
  return true;
}

// =====================================================================
// INFERENCE
// =====================================================================
void finishWindow() {
  windowCount++;
  float raw[F_COUNT] = {0};
  bool okG = computeGsrFeatures(raw);
  bool okP = computePpgFeatures(raw);

  Serial.printf("\n=== Window #%lu (%lu s) ===\n", (unsigned long)windowCount, (unsigned long)WINDOW_SEC);
  if (!okG || !okP) {
    Serial.printf("Window tidak valid (GSR %s, PPG %s | beat=%u, gsr=%u/%u, gsr_bad=%u)\n",
                  okG ? "OK" : "GAGAL", okP ? "OK" : "GAGAL", nIbi, gsrN, GSR_BUF_N, gsrBad);
    return;
  }

  Serial.printf("GSR : mean=%.3f uS | std=%.3f | slope=%.4f uS/s | SCR=%d\n",
                raw[F_GSR_MEAN], raw[F_GSR_STD], raw[F_GSR_SLOPE], (int)raw[F_SCR_COUNT]);
  Serial.printf("PPG : HR=%.1f bpm | SDNN=%.1f ms | RMSSD=%.1f ms | PI=%.2f %% | pNN50=%.1f %% | beat=%u\n",
                raw[F_HR_MEAN], raw[F_SDNN], raw[F_RMSSD], raw[F_PI], raw[F_PNN50], nIbi);

  // Standardisasi lalu prediksi
  float x[F_COUNT];
  for (uint8_t i = 0; i < F_COUNT; i++) x[i] = (raw[i] - SCALER_MEAN[i]) / SCALER_STD[i];
  float hydration = hydration_et_predict(x, F_COUNT);

  Serial.printf("Output model hidrasi: %.2f%s\n", hydration,
                SCALER_READY ? "" : "  (PERINGATAN: SCALER belum diisi, hasil tidak valid)");
}

// =====================================================================
// MAIN
// =====================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_GSR, ADC_11db);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);

  if (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("ERROR: MAX30102 tidak terdeteksi");
    while (true) delay(1000);
  }
  // LED 0x1F, avg 1, mode Red+IR, 50 sps, pulse width 411 us, ADC range 4096
  sensor.setup(0x1F, 1, 2, PPG_FS, 411, 4096);
  sensor.disableFIFORollover();

  Serial.println("MAX30102 siap. Tempelkan jari dan elektroda GSR.");
  if (!SCALER_READY) Serial.println("PERINGATAN: isi SCALER_MEAN/SCALER_STD dulu agar prediksi valid.");
}

void loop() {
  // Baca semua sampel PPG yang ada di FIFO
  sensor.check();
  while (sensor.available()) {
    onPpgSample(sensor.getFIFOIR());
    sensor.nextSample();
  }

  sampleGsr();

  // Window selesai -> hitung fitur & prediksi, lalu mulai window berikutnya
  if (windowActive && millis() - windowStartMs >= WINDOW_SEC * 1000UL) {
    finishWindow();
    startWindow();
  }

  // Status progres tiap 5 detik
  if (windowActive && millis() - lastStatusMs >= 5000) {
    lastStatusMs = millis();
    Serial.printf("[%lu/%lu s] beat=%u | GSR=%.2f uS\n",
                  (millis() - windowStartMs) / 1000, (unsigned long)WINDOW_SEC, nIbi, lastGsr);
  }

  delay(1);
}
