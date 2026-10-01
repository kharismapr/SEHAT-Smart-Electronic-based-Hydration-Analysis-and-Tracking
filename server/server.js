import express from 'express';
import cors from 'cors';
import { MeasurementRepository } from './db.js';

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

// Seed sample records on initial start if empty
MeasurementRepository.seedDemoDataIfEmpty();

// Health Check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'healthy',
    system: 'SEHAT Biometric Telemetry Server',
    database: 'SQLite (WAL Mode)',
    time: new Date().toISOString()
  });
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
    const latest = MeasurementRepository.getLatest();
    if (!latest) {
      return res.status(404).json({ success: false, message: 'No records found' });
    }
    res.json({ success: true, data: latest });
  } catch (error) {
    console.error('Error fetching latest measurement:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST new measurement (from React Dashboard or ESP32 / Wearable)
app.post('/api/measurements', (req, res) => {
  try {
    const { bpm, gsr, temperature, humidity, hoursSinceHydration, predictedHoursSinceHydration, notes, id, timestamp } = req.body;

    if (bpm === undefined && gsr === undefined && temperature === undefined && humidity === undefined) {
      return res.status(400).json({
        success: false,
        error: 'Missing required sensor features (bpm, gsr, temperature, humidity)'
      });
    }

    const newRecord = MeasurementRepository.insert({
      id,
      timestamp,
      bpm,
      gsr,
      temperature,
      humidity,
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
