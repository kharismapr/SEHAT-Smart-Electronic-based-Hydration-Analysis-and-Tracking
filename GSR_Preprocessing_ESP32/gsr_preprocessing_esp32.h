#pragma once

// GSR feature extraction for ESP32, matching the reprocessed training dataset.
// Input: calibrated skin conductance in microsiemens (uS), sampled at 51.2 Hz.
// This is a windowed, zero-phase filter: features are available after a window
// has been collected. Do not pass uncalibrated ADC counts or resistance here.

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace sehat_gsr {

constexpr double kSamplingHz = 51.2;
constexpr double kCutoffHz = 1.0;
constexpr size_t kWindowSamples = 1536;  // 30 s at 51.2 Hz
constexpr size_t kHopSamples = 768;      // 50% overlap
constexpr size_t kPadSamples = 9;        // scipy.signal.filtfilt default for 3 taps
constexpr size_t kWorkSamples = kWindowSamples + 2 * kPadSamples;

struct Features {
  double gsr_mean = std::numeric_limits<double>::quiet_NaN();
  double gsr_var = std::numeric_limits<double>::quiet_NaN();
  double gsr_entropy = std::numeric_limits<double>::quiet_NaN();
  size_t window_samples = 0;
  size_t interpolated_samples = 0;
  bool valid = false;
};

// Save these three means and sample standard deviations (pandas std, ddof=1)
// from the subject's training/calibration windows. Do not estimate them from
// the window being predicted; that would differ from the notebook's pipeline.
struct Calibration {
  double mean[3];  // gsr_mean, gsr_var, gsr_entropy
  double std[3];
};

struct NormalizedFeatures {
  double gsr_mean;
  double gsr_var;
  double gsr_entropy;
};

inline bool normalizeFeatures(const Features& raw, const Calibration& calibration,
                              NormalizedFeatures& out) {
  if (!raw.valid) return false;
  const double values[3] = {raw.gsr_mean, raw.gsr_var, raw.gsr_entropy};
  double normalized[3];
  for (size_t i = 0; i < 3; ++i) {
    if (!std::isfinite(calibration.mean[i])) return false;
    const double sigma = std::isfinite(calibration.std[i]) &&
                                 calibration.std[i] != 0.0
                             ? calibration.std[i]
                             : 1.0;
    normalized[i] = (values[i] - calibration.mean[i]) / sigma;
  }
  out = {normalized[0], normalized[1], normalized[2]};
  return true;
}

// Shimmer's GSR resistance is reported in kOhms. Use this only if the device
// really supplies calibrated resistance, not its raw ADC output.
inline float conductanceFromKohm(float resistance_kohm) {
  return std::isfinite(resistance_kohm) && resistance_kohm > 0.0f
             ? 1000.0f / resistance_kohm
             : std::numeric_limits<float>::quiet_NaN();
}

namespace detail {

struct Butterworth2 {
  double b0, b1, b2, a1, a2;

  Butterworth2() {
    const double pi = 3.14159265358979323846;
    const double k = std::tan(pi * kCutoffHz / kSamplingHz);
    const double root2 = std::sqrt(2.0);
    const double scale = 1.0 / (1.0 + root2 * k + k * k);
    b0 = k * k * scale;
    b1 = 2.0 * b0;
    b2 = b0;
    a1 = 2.0 * (k * k - 1.0) * scale;
    a2 = (1.0 - root2 * k + k * k) * scale;
  }

  // Direct Form II transposed. zi corresponds to scipy.signal.lfilter_zi
  // multiplied by the first value of the pass.
  void pass(double* data, size_t count, bool backwards) const {
    const double first = data[backwards ? count - 1 : 0];
    double z1 = (1.0 - b0) * first;
    double z2 = (b2 - a2) * first;
    for (size_t i = 0; i < count; ++i) {
      const size_t j = backwards ? count - 1 - i : i;
      const double x = data[j];
      const double y = b0 * x + z1;
      const double next_z1 = b1 * x - a1 * y + z2;
      z2 = b2 * x - a2 * y;
      z1 = next_z1;
      data[j] = y;
    }
  }
};

}  // namespace detail

// work must contain at least count + 18 doubles for count > 9, otherwise count.
// No heap allocation. NaN/Inf values are linearly interpolated, with edge gaps
// filled by the nearest valid observation (as in pandas interpolate both ways).
inline bool extractFeatures(const float* conductance_us, size_t count,
                            double* work, size_t work_capacity,
                            Features& out) {
  out = Features{};
  out.window_samples = count;
  if (!conductance_us || !work || !count) return false;

  const bool do_filter = count > kPadSamples;
  const size_t offset = do_filter ? kPadSamples : 0;
  const size_t total = count + 2 * offset;
  if (work_capacity < total) return false;

  size_t first_valid = count;
  for (size_t i = 0; i < count; ++i) {
    work[offset + i] = conductance_us[i];
    if (std::isfinite(work[offset + i]) && first_valid == count) first_valid = i;
    if (!std::isfinite(work[offset + i])) ++out.interpolated_samples;
  }
  if (first_valid == count) return false;

  const double first_value = work[offset + first_valid];
  for (size_t i = 0; i < first_valid; ++i) work[offset + i] = first_value;
  size_t previous = first_valid;
  for (size_t i = first_valid + 1; i < count; ++i) {
    if (!std::isfinite(work[offset + i])) continue;
    const double left = work[offset + previous];
    const double right = work[offset + i];
    for (size_t j = previous + 1; j < i; ++j) {
      work[offset + j] = left + (right - left) *
                                  (static_cast<double>(j - previous) / (i - previous));
    }
    previous = i;
  }
  for (size_t i = previous + 1; i < count; ++i)
    work[offset + i] = work[offset + previous];

  // A stuck/constant sensor has no meaningful histogram range. NumPy's
  // histogram can fail on the tiny filtfilt roundoff spread of such a signal;
  // reject it instead of passing an arbitrary entropy to the model.
  double raw_min = work[offset], raw_max = work[offset];
  for (size_t i = 1; i < count; ++i) {
    if (work[offset + i] < raw_min) raw_min = work[offset + i];
    if (work[offset + i] > raw_max) raw_max = work[offset + i];
  }
  if (raw_min == raw_max) return false;

  if (do_filter) {
    // scipy.signal.filtfilt(..., padtype="odd", padlen=9):
    // reflect nine samples about each endpoint, then filter forward/backward.
    for (size_t i = 0; i < kPadSamples; ++i) {
      work[i] = 2.0 * work[offset] - work[offset + kPadSamples - i];
      work[offset + count + i] = 2.0 * work[offset + count - 1] -
                                 work[offset + count - 2 - i];
    }
    const detail::Butterworth2 filter;
    filter.pass(work, total, false);
    filter.pass(work, total, true);
  }

  double sum = 0.0;
  double minimum = work[offset];
  double maximum = minimum;
  for (size_t i = 0; i < count; ++i) {
    const double value = work[offset + i];
    if (!std::isfinite(value)) return false;
    sum += value;
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
  }
  const double mean = sum / count;
  double squared_error = 0.0;
  uint32_t bins[10] = {};
  for (size_t i = 0; i < count; ++i) {
    const double value = work[offset + i];
    const double delta = value - mean;
    squared_error += delta * delta;
    int bin = 0;
    if (maximum > minimum) {
      bin = static_cast<int>(10.0 * (value - minimum) / (maximum - minimum));
      if (bin > 9) bin = 9;  // NumPy includes the maximum in the final bin.
      if (bin < 0) bin = 0;
    }
    ++bins[bin];
  }

  double entropy = 0.0;
  for (uint32_t hits : bins) {
    if (!hits) continue;
    const double probability = static_cast<double>(hits) / count;
    entropy -= probability * std::log(probability);  // natural log, scipy.stats.entropy
  }
  out.gsr_mean = mean;
  out.gsr_var = squared_error / count;  // numpy.var: ddof=0
  out.gsr_entropy = entropy;
  out.valid = true;
  return true;
}

// Place this object in static/global storage on ESP32. It owns about 18 KB of
// buffers and emits a new feature row every 768 samples after the first 1536.
class Processor {
 public:
  bool addSample(float conductance_us, Features& out) {
    samples_[count_++] = conductance_us;
    ++new_samples_;
    if (count_ < kWindowSamples) return false;
    extractFeatures(samples_, count_, work_, kWorkSamples, out);
    std::memmove(samples_, samples_ + kHopSamples,
                 (kWindowSamples - kHopSamples) * sizeof(samples_[0]));
    count_ = kWindowSamples - kHopSamples;
    new_samples_ = 0;
    return true;  // out.valid is false for all-missing or constant readings.
  }

  // Call once at the end of a recording to emit its uncovered partial tail.
  bool flush(Features& out) {
    if (!new_samples_) return false;
    extractFeatures(samples_, count_, work_, kWorkSamples, out);
    reset();
    return true;
  }

  void reset() {
    count_ = 0;
    new_samples_ = 0;
  }

 private:
  float samples_[kWindowSamples] = {};
  double work_[kWorkSamples] = {};
  size_t count_ = 0;
  size_t new_samples_ = 0;
};

}  // namespace sehat_gsr
