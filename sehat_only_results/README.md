# SEHAT-only Extra Trees export

Training: 19 raw recordings, 19 retained recordings, 350 accepted windows, 5 subjects. No Shimmer training data.

Uses the hybrid notebook's fixed preprocessing/QC and Extra Trees configuration. LOSO fits its imputer on each training fold; the deployment model is refit on all accepted SEHAT windows.

Recording-level LOSO MAE: 2.423100 h; RMSE: 2.978571 h. See evaluation_per_subject.csv and oof_predictions_recordings.csv.

The checked-in `SEHAT_GSR_PPG_ESP32_ML.ino` now includes `et_sehat_only.h`. It keeps `s1_features.h`, `s1_scaler.h`, the nine-feature order, the existing `hydration_et_predict(input, 9)` call, and hours output. The new header internally reverses the old scaler and applies its trained imputer. Include one model header at a time.

Regenerate: `python scripts/export_et_sehat_only.py`. Verify: `python tests/verify_sehat_only_export.py`.

Host numerical checks do not validate the ESP32 board or equivalence of HeartPy and the embedded peak detector. This is an estimated duration proxy evaluated on five subjects.
