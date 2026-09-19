/* Baseline Linear Regression Model for TinyML (ESP32) */
/* Generated for SEHAT Hydration Tracking System */
#ifndef HYDRATION_LR_H
#define HYDRATION_LR_H

#ifdef __cplusplus
extern "C" {
#endif

#define HYDRATION_LR_NUM_FEATURES 9

// Feature order: gsr_mean, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn, pnn50, n_peaks, ppg_available
static const float hydration_lr_intercept = 9.004027f;
static const float hydration_lr_weights[HYDRATION_LR_NUM_FEATURES] = {
       -0.930325f, // gsr_mean
        0.030700f, // gsr_var
        0.015649f, // gsr_entropy
       -0.032782f, // mean_hr
       -0.006689f, // rmssd
       -0.005885f, // sdnn
       -0.000521f, // pnn50
       -0.026602f, // n_peaks
        5.911134f // ppg_available
};

static inline float hydration_lr_predict(const float *features) {
    float prediction = hydration_lr_intercept;
    for (int i = 0; i < HYDRATION_LR_NUM_FEATURES; ++i) {
        prediction += hydration_lr_weights[i] * features[i];
    }
    return prediction;
}

#ifdef __cplusplus
}
#endif

#endif // HYDRATION_LR_H
