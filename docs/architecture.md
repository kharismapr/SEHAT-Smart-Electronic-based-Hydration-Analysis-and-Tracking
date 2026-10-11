# SEHAT Architecture

## Runtime flow

The intended production flow has one inference owner:

```text
MAX30102 + Grove GSR + optional MPU-9250
                |
                v
        ESP32 synchronized sampling
                |
                v
      30-second S1 feature windows
                |
                v
       Embedded ExtraTrees inference
                |
                v
        Telemetry API ingestion
                |
                v
             SQLite
                |
                v
             Dashboard
```

The ESP32 is the production owner of signal processing, feature extraction, normalization, and S1 model inference. The API stores and serves measurements and prediction results. The dashboard presents those results.

## Repository boundaries

- `firmware/` owns board-specific acquisition and embedded preprocessing.
- `ml/` owns experiments, training data preparation, host reference implementations, and export inputs.
- `tools/` owns repeatable commands that generate datasets, scalers, or deployment artifacts.
- `apps/api/` owns transport and persistence, not an undocumented replacement model.
- `apps/dashboard/` owns presentation and development simulation adapters.
- `tests/` owns cross-boundary consistency checks.

## Development simulation

The dashboard may use simulated telemetry for UI development. Simulation must be explicit in code and documentation; it must not be confused with ESP32 model output. The API heuristic currently used for demo records must be treated as demo behavior until it is replaced by or explicitly versioned as a production model.

## Migration rule

Directory moves should preserve behavior first. Algorithm changes, model retraining, hardware changes, and UI redesign are separate changes and should not be mixed into the repository reorganization.
