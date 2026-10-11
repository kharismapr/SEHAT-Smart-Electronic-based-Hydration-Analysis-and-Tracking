#pragma once

// PPG preprocessing for ESP32. Companion to MAX30102_Preprocessing_ESP32.ino.
// The numerical filters and window sizes follow ppg_preprocessing.py. Peak/HRV
// extraction below is an embedded approximation, NOT a HeartPy port.

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace sehat_ppg {

constexpr double kFs = 51.2;
constexpr size_t kWindow = 1536;             // 30 seconds
constexpr size_t kHop = 768;                // 50% overlap
constexpr size_t kPad = 15;                // scipy sosfiltfilt, two SOS sections
constexpr size_t kWork = kWindow + 2 * kPad;
constexpr size_t kMaxPeaks = 128;
constexpr size_t kMaxRepair = 12;          // floor(0.25 seconds * 51.2 Hz)

enum class Status : uint8_t {
  ok, too_short, missing_ppg, flat_signal, insufficient_valid_beats,
  review_bpm_range, review_rr_rejections
};

inline const char* statusName(Status status) {
  switch (status) {
    case Status::ok: return "ok";
    case Status::too_short: return "too_short";
    case Status::missing_ppg: return "missing_ppg";
    case Status::flat_signal: return "flat_signal";
    case Status::insufficient_valid_beats: return "insufficient_valid_beats";
    case Status::review_bpm_range: return "review_bpm_range";
    case Status::review_rr_rejections: return "review_rr_rejections";
  }
  return "unknown";
}

struct Features {
  double ibi = NAN;                     // ms
  double bpm = NAN;                     // beats/min
  double mean_hr = NAN;                 // same as bpm, model column
  double rmssd = NAN;                   // ms
  double sdnn = NAN;                    // ms
  double pnn50 = NAN;                   // percent, as in training
  double rr_rejected_fraction = NAN;
  float gyro_missing_fraction = 1.0f;
  float high_motion_fraction = 0.0f;
  float ppg_interpolated_fraction = 0.0f;
  uint16_t n_peaks = 0;
  uint16_t window_samples = 0;
  Status status = Status::too_short;
  bool ppg_feature_valid = false;
  bool ppg_quality_ok = false;
  uint8_t ppg_available = 0;
};

namespace detail {

struct Sos { double b0, b1, b2, a1, a2; };

// scipy.signal.butter(4, cutoff, btype=..., fs=51.2, output="sos")
constexpr Sos kHighpass05[2] = {
  {0.92294610320087456, -1.8458922064017491, 0.92294610320087456,
   -1.8892070305516262, 0.89276900813102533},
  {1.0, -2.0, 1.0, -1.9504657579301043, 0.95414323487507646}
};
constexpr Sos kLowpass4[2] = {
  {0.0020570668221922155, 0.0041141336443844311, 0.0020570668221922155,
   -1.2287186180807916, 0.39322938197740648},
  {1.0, 2.0, 1.0, -1.494280686499329, 0.69434704310417295}
};
constexpr Sos kLowpass25[2] = {
  {0.00038202096079826365, 0.00076404192159652731, 0.00038202096079826365,
   -1.4906853535747362, 0.56370073247504338},
  {1.0, 2.0, 1.0, -1.7090881897476977, 0.79280117548893181}
};

inline size_t reflectIndex(int index, size_t count) {
  if (count == 1) return 0;
  while (index < 0 || index >= static_cast<int>(count)) {
    if (index < 0) index = -index - 1;
    else index = 2 * static_cast<int>(count) - index - 1;
  }
  return static_cast<size_t>(index);
}

inline void passSos(double* data, size_t count, const Sos& s, bool reverse) {
  const double first = data[reverse ? count - 1 : 0];
  const double gain = (s.b0 + s.b1 + s.b2) / (1.0 + s.a1 + s.a2);
  double z1 = (gain - s.b0) * first;
  double z2 = (s.b2 - s.a2 * gain) * first;
  for (size_t i = 0; i < count; ++i) {
    const size_t j = reverse ? count - 1 - i : i;
    const double x = data[j];
    const double y = s.b0 * x + z1;
    const double next_z1 = s.b1 * x - s.a1 * y + z2;
    z2 = s.b2 * x - s.a2 * y;
    z1 = next_z1;
    data[j] = y;
  }
}

inline double parabolaPeak(const float* signal, size_t i) {
  const double a = signal[i - 1], b = signal[i], c = signal[i + 1];
  const double denominator = a - 2.0 * b + c;
  if (denominator >= -1e-12) return static_cast<double>(i);
  double offset = 0.5 * (a - c) / denominator;
  if (offset < -0.5) offset = -0.5;
  if (offset > 0.5) offset = 0.5;
  return i + offset;
}

}  // namespace detail

// About 53 KB of buffers. Declare globally/static, not inside loop().
class Processor {
 public:
  bool addSample(float ir, float gyro_magnitude, Features& out) {
    raw_[count_] = ir;
    gyro_[count_] = gyro_magnitude;
    ++count_;
    ++new_samples_;
    if (count_ < kWindow) return false;
    process(count_, out);
    std::memmove(raw_, raw_ + kHop, (kWindow - kHop) * sizeof(raw_[0]));
    std::memmove(gyro_, gyro_ + kHop, (kWindow - kHop) * sizeof(gyro_[0]));
    count_ = kWindow - kHop;
    new_samples_ = 0;
    return true;
  }

  bool flush(Features& out) {
    if (!new_samples_) return false;
    process(count_, out);
    reset();
    return true;
  }

  void reset() { count_ = new_samples_ = 0; }

  // Valid until the next addSample() that completes a window.
  const float* lastCleaned() const { return smoothed_; }

 private:
  float raw_[kWindow] = {};
  float gyro_[kWindow] = {};
  float baseline_[kWindow] = {};
  float low_[kWindow] = {};
  float motion_score_[kWindow] = {};
  float smoothed_[kWindow] = {};
  double work_[kWork] = {};
  double peak_index_[kMaxPeaks] = {};
  float peak_height_[kMaxPeaks] = {};
  double rr_[kMaxPeaks] = {};
  double sorted_rr_[kMaxPeaks] = {};
  bool rr_valid_[kMaxPeaks] = {};
  size_t count_ = 0;
  size_t new_samples_ = 0;

  bool repairPpg(size_t count, Features& out) {
    for (size_t i = 0; i < count; ++i) baseline_[i] = raw_[i];
    if (!std::isfinite(baseline_[0]) || !std::isfinite(baseline_[count - 1]))
      return false;
    size_t previous = 0;
    for (size_t i = 1; i < count; ++i) {
      if (!std::isfinite(baseline_[i])) continue;
      const size_t gap = i - previous - 1;
      if (gap > kMaxRepair) return false;
      for (size_t j = previous + 1; j < i; ++j) {
        baseline_[j] = baseline_[previous] +
            (baseline_[i] - baseline_[previous]) *
            (static_cast<float>(j - previous) / (i - previous));
      }
      out.ppg_interpolated_fraction += static_cast<float>(gap) / count;
      previous = i;
    }
    return previous == count - 1;
  }

  void filter(const float* input, size_t count, const detail::Sos* sos,
              float* output) {
    for (size_t i = 0; i < count; ++i) work_[kPad + i] = input[i];
    for (size_t i = 0; i < kPad; ++i) {
      work_[i] = 2.0 * work_[kPad] - work_[2 * kPad - i];
      work_[kPad + count + i] = 2.0 * work_[kPad + count - 1] -
                                  work_[kPad + count - 2 - i];
    }
    const size_t total = count + 2 * kPad;
    for (size_t s = 0; s < 2; ++s) detail::passSos(work_, total, sos[s], false);
    for (size_t s = 0; s < 2; ++s) detail::passSos(work_, total, sos[s], true);
    for (size_t i = 0; i < count; ++i) output[i] = static_cast<float>(work_[kPad + i]);
  }

  void computeMotion(size_t count, Features& out) {
    size_t missing = 0;
    for (size_t i = 0; i < count; ++i) {
      work_[kPad + i] = gyro_[i];
      if (!std::isfinite(work_[kPad + i])) ++missing;
      motion_score_[i] = NAN;
    }
    // Gyro short interior gaps receive the same interpolation limit as PPG.
    size_t i = 0;
    while (i < count) {
      if (std::isfinite(work_[kPad + i])) { ++i; continue; }
      const size_t start = i;
      while (i < count && !std::isfinite(work_[kPad + i])) ++i;
      if (start == 0 || i == count || i - start > kMaxRepair) continue;
      const double left = work_[kPad + start - 1];
      const double right = work_[kPad + i];
      for (size_t j = start; j < i; ++j)
        work_[kPad + j] = left + (right - left) *
            (static_cast<double>(j - start + 1) / (i - start + 1));
    }
    out.gyro_missing_fraction = static_cast<float>(missing) / count;

    double score_sum = 0.0;
    size_t score_count = 0;
    i = 0;
    while (i < count) {
      if (!std::isfinite(work_[kPad + i])) { ++i; continue; }
      const size_t start = i;
      while (i < count && std::isfinite(work_[kPad + i])) ++i;
      const size_t length = i - start;
      for (size_t j = 0; j < length; ++j) {
        double total = 0.0;
        for (int lag = -25; lag <= 25; ++lag) {
          const size_t k = detail::reflectIndex(static_cast<int>(j) + lag, length);
          if (k != 0) total += std::abs(work_[kPad + start + k] -
                                         work_[kPad + start + k - 1]);
        }
        motion_score_[start + j] = static_cast<float>(total / 51.0);
        score_sum += motion_score_[start + j];
        ++score_count;
      }
    }
    if (!score_count) return;
    const double threshold = score_sum / score_count;
    size_t high = 0;
    for (size_t j = 0; j < count; ++j)
      if (std::isfinite(motion_score_[j]) && motion_score_[j] > threshold) ++high;
    out.high_motion_fraction = static_cast<float>(high) / count;
    if (!high) return;

    filter(baseline_, count, detail::kLowpass25, smoothed_);
    for (size_t j = 0; j < count; ++j) {
      double blend = 0.0;
      for (int lag = -6; lag <= 6; ++lag) {
        const size_t k = detail::reflectIndex(static_cast<int>(j) + lag, count);
        if (std::isfinite(motion_score_[k]) && motion_score_[k] > threshold)
          blend += 1.0;
      }
      blend /= 13.0;
      if (!std::isfinite(motion_score_[j])) blend = 0.0;
      low_[j] = static_cast<float>((1.0 - blend) * low_[j] + blend * smoothed_[j]);
    }
  }

  void extractPeaks(size_t count, Features& out) {
    double mean = 0.0, minimum = smoothed_[0], maximum = smoothed_[0];
    double max_abs = std::abs(smoothed_[0]);
    for (size_t i = 0; i < count; ++i) {
      const double value = smoothed_[i];
      if (!std::isfinite(value)) { out.status = Status::missing_ppg; return; }
      mean += value;
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
      if (std::abs(value) > max_abs) max_abs = std::abs(value);
    }
    mean /= count;
    if (maximum - minimum <= std::fmax(1e-8, max_abs * 1e-10)) {
      out.status = Status::flat_signal;
      return;
    }
    double variance = 0.0;
    for (size_t i = 0; i < count; ++i) {
      const double delta = smoothed_[i] - mean;
      variance += delta * delta;
    }
    const double threshold = mean + 0.35 * std::sqrt(variance / count);
    size_t peaks = 0;
    for (size_t i = 1; i + 1 < count; ++i) {
      if (smoothed_[i] < threshold || smoothed_[i] < smoothed_[i - 1] ||
          smoothed_[i] <= smoothed_[i + 1]) continue;
      const double position = detail::parabolaPeak(smoothed_, i);
      if (peaks && position - peak_index_[peaks - 1] < 17.0) {
        if (smoothed_[i] > peak_height_[peaks - 1]) {
          peak_index_[peaks - 1] = position;
          peak_height_[peaks - 1] = smoothed_[i];
        }
      } else if (peaks < kMaxPeaks) {
        peak_index_[peaks] = position;
        peak_height_[peaks] = smoothed_[i];
        ++peaks;
      }
    }
    out.n_peaks = static_cast<uint16_t>(peaks);
    if (peaks < 4) { out.status = Status::insufficient_valid_beats; return; }

    const size_t interval_count = peaks - 1;
    size_t plausible = 0;
    for (size_t i = 0; i < interval_count; ++i) {
      rr_[i] = (peak_index_[i + 1] - peak_index_[i]) * (1000.0 / kFs);
      rr_valid_[i] = rr_[i] >= 1000.0 / 3.0 && rr_[i] <= 1500.0;
      if (rr_valid_[i]) sorted_rr_[plausible++] = rr_[i];
    }
    if (plausible < 3) { out.status = Status::insufficient_valid_beats; return; }
    for (size_t i = 1; i < plausible; ++i) {
      const double value = sorted_rr_[i];
      size_t j = i;
      while (j && sorted_rr_[j - 1] > value) {
        sorted_rr_[j] = sorted_rr_[j - 1];
        --j;
      }
      sorted_rr_[j] = value;
    }
    const double median = sorted_rr_[plausible / 2];
    size_t valid = 0;
    double sum = 0.0;
    for (size_t i = 0; i < interval_count; ++i) {
      rr_valid_[i] = rr_valid_[i] && rr_[i] >= 0.70 * median &&
                     rr_[i] <= 1.30 * median;
      if (rr_valid_[i]) { sum += rr_[i]; ++valid; }
    }
    out.rr_rejected_fraction = static_cast<double>(interval_count - valid) /
                               interval_count;
    if (valid < 3) { out.status = Status::insufficient_valid_beats; return; }
    out.ibi = sum / valid;
    out.bpm = 60000.0 / out.ibi;
    out.mean_hr = out.bpm;
    double sd_sum = 0.0, diff_sum = 0.0;
    size_t adjacent = 0, over_50 = 0;
    for (size_t i = 0; i < interval_count; ++i) {
      if (!rr_valid_[i]) continue;
      const double delta = rr_[i] - out.ibi;
      sd_sum += delta * delta;
      if (i && rr_valid_[i - 1]) {
        const double difference = rr_[i] - rr_[i - 1];
        diff_sum += difference * difference;
        ++adjacent;
        if (std::abs(difference) > 50.0) ++over_50;
      }
    }
    if (!adjacent) { out.status = Status::insufficient_valid_beats; return; }
    out.sdnn = std::sqrt(sd_sum / (valid - 1));
    out.rmssd = std::sqrt(diff_sum / adjacent);
    out.pnn50 = 100.0 * over_50 / adjacent;
    out.ppg_feature_valid = std::isfinite(out.bpm) && std::isfinite(out.rmssd) &&
                            std::isfinite(out.sdnn) && std::isfinite(out.pnn50) &&
                            out.bpm >= 40.0 && out.bpm <= 180.0;
    out.ppg_available = out.ppg_feature_valid ? 1 : 0;
    out.ppg_quality_ok = out.ppg_feature_valid &&
                         out.rr_rejected_fraction <= 0.30;
    out.status = !out.ppg_feature_valid ? Status::review_bpm_range :
                 !out.ppg_quality_ok ? Status::review_rr_rejections : Status::ok;
  }

  void process(size_t count, Features& out) {
    out = Features{};
    out.window_samples = static_cast<uint16_t>(count);
    if (count < 256) return;  // notebook requires at least ceil(5 * 51.2)
    if (!repairPpg(count, out)) { out.status = Status::missing_ppg; return; }
    filter(baseline_, count, detail::kHighpass05, baseline_);
    filter(baseline_, count, detail::kLowpass4, low_);
    computeMotion(count, out);  // all missing gyro -> low-motion 4 Hz branch
    for (size_t i = 0; i < count; ++i) {
      double total = 0.0;
      for (int lag = -4; lag <= 4; ++lag)
        total += low_[detail::reflectIndex(static_cast<int>(i) + lag, count)];
      smoothed_[i] = static_cast<float>(total / 9.0);
    }
    extractPeaks(count, out);
  }
};

}  // namespace sehat_ppg
