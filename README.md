# SEHAT

Smart Electronic-based Hydration Analysis and Tracking.

SEHAT combines ESP32 biosignal acquisition, host-side preprocessing and model validation, a local telemetry API, and a dashboard for reviewing measurements.

## Repository layout

- `firmware/` - supported ESP32 firmware and hardware prototypes.
- `ml/` - training notebooks and reusable host-side preprocessing/model code.
- `data/` - processed datasets and reproducible summaries; raw recordings stay local.
- `apps/dashboard/` - React/Vite dashboard.
- `apps/api/` - local telemetry API and SQLite persistence.
- `tools/` - data reprocessing and model/scaler generation commands.
- `tests/` - Python, firmware, and integration checks.
- `docs/` - architecture and data/model contracts.

The repository uses the layout above. The supported firmware is in `firmware/esp32/sehat-s1-ml/`; the dashboard and API are in `apps/dashboard/` and `apps/api/`.

## Production data flow

```text
ESP32 sensors -> S1 feature extraction and inference -> API -> SQLite -> dashboard
```

The ESP32 S1 path currently produces an estimated fasting duration in hours. It is not a clinical hydration percentage or diagnosis. See [docs/data-and-model-contract.md](docs/data-and-model-contract.md) for the feature and payload contract.

## Current validation commands

From the repository root:

```powershell
.venv/Scripts/python -m unittest discover -s tests/python -v
.venv/Scripts/python tests/firmware/verify_s1_consistency.py
```

Dashboard commands run from `apps/dashboard/`:

```powershell
npm install
npm run lint
npm run build
```

API commands run from `apps/api/`:

```powershell
npm install
npm start
```

Raw recordings and local SQLite state are not repository source artifacts. Do not commit them.
