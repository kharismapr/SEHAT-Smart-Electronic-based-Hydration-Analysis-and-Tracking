#pragma once

#include <cmath>
#include <cstddef>

#include "gsr_preprocessing_esp32.h"
#include "ppg_preprocessing_esp32.h"
#include "s1_scaler.h"

namespace sehat_s1 {

enum FeatureIndex : size_t {
  gsr_mean = 0, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn, pnn50,
  n_peaks, ppg_available, feature_count
};

static_assert(feature_count == 9, "ExtraTrees S1 requires nine inputs");
static_assert(sehat_gsr::kWindowSamples == sehat_ppg::kWindow,
              "GSR and PPG windows must have the same size");
static_assert(sehat_gsr::kHopSamples == sehat_ppg::kHop,
              "GSR and PPG hops must have the same size");

// The first eight columns receive the personal S1 pandas z-score (ddof=1).
// Invalid PPG is zero in normalized space; the final availability flag is raw.
inline bool makeModelInput(const sehat_gsr::Features& gsr,
                           const sehat_ppg::Features& ppg,
                           float (&out)[feature_count]) {
  if (!gsr.valid || gsr.window_samples != ppg.window_samples) return false;
  const double raw[8] = {
      gsr.gsr_mean, gsr.gsr_var, gsr.gsr_entropy,
      ppg.mean_hr, ppg.rmssd, ppg.sdnn, ppg.pnn50,
      static_cast<double>(ppg.n_peaks)
  };
  bool ppg_valid = ppg.ppg_available == 1 && ppg.ppg_feature_valid;
  if (ppg_valid) {
    for (size_t i = mean_hr; i <= n_peaks; ++i) {
      if (!std::isfinite(raw[i]) || raw[i] == -1.0) {
        ppg_valid = false;
        break;
      }
    }
  }
  for (size_t i = 0; i < 8; ++i) {
    if (i >= mean_hr && !ppg_valid) {
      out[i] = 0.0f;
      continue;
    }
    if (!std::isfinite(raw[i]) || !std::isfinite(kMean[i]) ||
        !std::isfinite(kStd[i]) || kStd[i] <= 0.0) return false;
    const double normalized = (raw[i] - kMean[i]) / kStd[i];
    if (!std::isfinite(normalized)) return false;
    out[i] = static_cast<float>(normalized);
    if (!std::isfinite(out[i])) return false;
  }
  out[ppg_available] = ppg_valid ? 1.0f : 0.0f;
  return true;
}

}  // namespace sehat_s1
