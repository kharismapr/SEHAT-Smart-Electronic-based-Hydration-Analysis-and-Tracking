import express from 'express';
import cors from 'cors';
import { MeasurementRepository } from './db.js';

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

// Seed sample records on initial start if empty
MeasurementRepository.seedDemoDataIfEmpty();

// Ephemeral in-memory live sensor stream (does NOT write to SQLite DB)
let liveTelemetry = {
  bpm: 72,
  spo2: null,
  spo2Valid: false,
  gsr: 9.5,
  rmssd: 32,
  predictedHours: null,
  isLive: false,
  timestamp: Date.now()
};

// Device Command Queue (e.g. 'c' = calibrate, 's' = start, 'f' = flush, 'r' = reset)
let pendingCommands = [];

// Health Check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'healthy',
    system: 'SEHAT Biometric Telemetry Server',
    database: 'SQLite (WAL Mode)',
    time: new Date().toISOString()
  });
});

// GET /api/telemetry/live (Current live sensor state for UI gauges)
app.get('/api/telemetry/live', (req, res) => {
  const ageMs = Date.now() - liveTelemetry.timestamp;
  res.json({
    success: true,
    data: {
      ...liveTelemetry,
      isLive: ageMs < 5000 // Active if updated within last 5 seconds
    }
  });
});

// POST /api/telemetry/live (Streamed from Bridge every 250ms, no DB write)
app.post('/api/telemetry/live', (req, res) => {
  const { bpm, spo2, spo2Valid, gsr, rmssd, predictedHours } = req.body;
  const spo2Value = spo2 == null ? null : Number(spo2);
  const validSpo2 = spo2Valid === true && spo2Value !== null && Number.isFinite(spo2Value) && spo2Value >= 0 && spo2Value <= 100;
  liveTelemetry = {
    bpm: Number(bpm ?? liveTelemetry.bpm),
    spo2: validSpo2 ? spo2Value : null,
    spo2Valid: validSpo2,
    gsr: Number(gsr ?? liveTelemetry.gsr),
    rmssd: Number(rmssd ?? liveTelemetry.rmssd),
    predictedHours: predictedHours != null ? Number(predictedHours) : liveTelemetry.predictedHours,
    isLive: true,
    timestamp: Date.now()
  };
  res.json({ success: true, data: liveTelemetry });
});

// POST /api/device/command (Send 'c', 's', 'f', 'r' from dashboard)
app.post('/api/device/command', (req, res) => {
  const { command } = req.body;
  if (!command) {
    return res.status(400).json({ success: false, error: 'Command required' });
  }
  pendingCommands.push(command.toString());
  console.log(`[Device Command Received from UI] -> '${command}'`);
  res.json({ success: true, message: `Command '${command}' queued` });
});

// GET /api/device/command (Polled by serial bridge to execute on ESP32)
app.get('/api/device/command', (req, res) => {
  const command = pendingCommands.shift() || null;
  res.json({ success: true, command });
});

// GET all measurements
app.get('/api/measurements', (req, res) => {
  try {
    const limit = parseInt(req.query.limit, 10) || 200;
    const records = MeasurementRepository.getAll(limit);
    res.json({
      success: true,
      count: records.length,
      data: records
    });
  } catch (error) {
    console.error('Error fetching measurements:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET latest measurement
app.get('/api/measurements/latest', (req, res) => {
  try {
    const record = MeasurementRepository.getLatest();
    if (!record) {
      return res.status(404).json({ success: false, message: 'No measurements found' });
    }
    res.json({ success: true, data: record });
  } catch (error) {
    console.error('Error fetching latest measurement:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST new measurement (from React Dashboard or ESP32 / Wearable)
app.post('/api/measurements', (req, res) => {
  try {
    const { bpm, spo2, spo2Valid, gsr, hoursSinceHydration, predictedHoursSinceHydration, notes, id, timestamp } = req.body;

    if (bpm === undefined && gsr === undefined) {
      return res.status(400).json({
        success: false,
        error: 'Missing required sensor features (bpm, gsr)'
      });
    }

    const newRecord = MeasurementRepository.insert({
      id,
      timestamp,
      bpm,
      spo2,
      spo2Valid,
      gsr,
      predictedHoursSinceHydration: predictedHoursSinceHydration ?? hoursSinceHydration,
      notes
    });

    res.status(201).json({
      success: true,
      message: 'Measurement recorded successfully',
      data: newRecord
    });
  } catch (error) {
    console.error('Error recording measurement:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// DELETE single measurement
app.delete('/api/measurements/:id', (req, res) => {
  try {
    MeasurementRepository.deleteById(req.params.id);
    res.json({ success: true, message: `Measurement ${req.params.id} deleted` });
  } catch (error) {
    console.error('Error deleting measurement:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// DELETE all measurements
app.delete('/api/measurements', (req, res) => {
  try {
    MeasurementRepository.clearAll();
    res.json({ success: true, message: 'All measurements cleared' });
  } catch (error) {
    console.error('Error clearing measurements:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`[SEHAT Server] Running on http://localhost:${PORT}`);
  console.log(`[SEHAT Server] SQLite DB active: server/sehat.db`);
});
