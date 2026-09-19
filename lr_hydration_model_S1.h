/* Baseline Linear Regression Model for TinyML (ESP32) */
/* Generated for SEHAT Hydration Tracking System */
#ifndef HYDRATION_LR_S1_H
#define HYDRATION_LR_S1_H

#ifdef __cplusplus
extern "C" {
#endif

#define HYDRATION_LR_S1_NUM_FEATURES 9

// Feature order: gsr_mean, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn, pnn50, n_peaks, ppg_available
static const float hydration_lr_s1_intercept = 8.846550f;
static const float hydration_lr_s1_weights[HYDRATION_LR_S1_NUM_FEATURES] = {
       -1.071391f, // gsr_mean
        0.005702f, // gsr_var
        0.122740f, // gsr_entropy
       -0.013438f, // mean_hr
       -0.005227f, // rmssd
       -0.002425f, // sdnn
       -0.001651f, // pnn50
       -0.070457f, // n_peaks
        5.794921f // ppg_available
};

static inline float hydration_lr_s1_predict(const float *features) {
    float prediction = hydration_lr_s1_intercept;
    for (int i = 0; i < HYDRATION_LR_S1_NUM_FEATURES; ++i) {
        prediction += hydration_lr_s1_weights[i] * features[i];
    }
    return prediction;
}

#ifdef __cplusplus
}
#endif

#endif // HYDRATION_LR_S1_H
