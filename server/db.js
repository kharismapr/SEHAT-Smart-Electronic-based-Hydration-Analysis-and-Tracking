import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DB_PATH = path.join(__dirname, 'sehat.db');

export const db = new DatabaseSync(DB_PATH);

// Initialize schema
db.exec(`
  PRAGMA journal_mode = WAL;

  CREATE TABLE IF NOT EXISTS measurements (
    id TEXT PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    bpm REAL NOT NULL,
    gsr REAL NOT NULL,
    temperature REAL NOT NULL,
    humidity REAL NOT NULL,
    predicted_hours_since_hydration REAL NOT NULL,
    status_key TEXT NOT NULL,
    notes TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_measurements_timestamp ON measurements(timestamp DESC);
`);

/**
 * Predicts hours since hydration based on biological regression heuristic
 * Matches client model: f(PPG, GSR, Temp, Humidity) -> Estimated Hours (y_hat)
 */
export function calculateInference(bpm, gsr, temperature, humidity) {
  const baselineGsr = 14.0;
  const gsrDeficit = Math.max(0, (baselineGsr - gsr) * 0.95);

  const baselineBpm = 68;
  const bpmDeficit = Math.max(0, (bpm - baselineBpm) * 0.09);

  const baselineTemp = 36.4;
  const tempDeficit = Math.max(0, (temperature - baselineTemp) * 1.6);

  const humidityCorrection = Math.max(0, (50 - humidity) * 0.03);

  const rawEstimate = gsrDeficit + bpmDeficit + tempDeficit + humidityCorrection;
  const boundedEstimate = Math.max(0.2, Math.min(24.0, rawEstimate));
  const predictedHours = parseFloat(boundedEstimate.toFixed(1));
  const statusKey = predictedHours > 10.0 ? 'AT_RISK' : 'WELL_HYDRATED';

  return { predictedHours, statusKey };
}

export const MeasurementRepository = {
  getAll(limit = 200) {
    const stmt = db.prepare(`
      SELECT 
        id,
        timestamp,
        created_at AS createdAt,
        bpm,
        gsr,
        temperature,
        humidity,
        predicted_hours_since_hydration AS hoursSinceHydration,
        predicted_hours_since_hydration AS predictedHoursSinceHydration,
        status_key AS statusKey,
        notes
      FROM measurements
      ORDER BY timestamp DESC
      LIMIT ?
    `);
    return stmt.all(limit);
  },

  getLatest() {
    const stmt = db.prepare(`
      SELECT 
        id,
        timestamp,
        created_at AS createdAt,
        bpm,
        gsr,
        temperature,
        humidity,
        predicted_hours_since_hydration AS hoursSinceHydration,
        predicted_hours_since_hydration AS predictedHoursSinceHydration,
        status_key AS statusKey,
        notes
      FROM measurements
      ORDER BY timestamp DESC
      LIMIT 1
    `);
    return stmt.get();
  },

  insert(record) {
    const id = record.id || `meas_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
    const timestamp = record.timestamp || Date.now();
    const createdAt = new Date(timestamp).toISOString();
    const bpm = Number(record.bpm ?? 72);
    const gsr = Number(record.gsr ?? 10);
    const temperature = Number(record.temperature ?? 36.5);
    const humidity = Number(record.humidity ?? 55);

    // If prediction is not provided by the sender, infer it on the server
    let predictedHours = record.predictedHoursSinceHydration ?? record.hoursSinceHydration;
    let statusKey = record.statusKey;

    if (predictedHours === undefined || predictedHours === null || Number.isNaN(Number(predictedHours))) {
      const inference = calculateInference(bpm, gsr, temperature, humidity);
      predictedHours = inference.predictedHours;
      statusKey = inference.statusKey;
    } else {
      predictedHours = Number(predictedHours);
      if (!statusKey) {
        statusKey = predictedHours > 10.0 ? 'AT_RISK' : 'WELL_HYDRATED';
      }
    }

    const stmt = db.prepare(`
      INSERT INTO measurements (
        id, timestamp, created_at, bpm, gsr, temperature, humidity,
        predicted_hours_since_hydration, status_key, notes
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      timestamp,
      createdAt,
      bpm,
      gsr,
      temperature,
      humidity,
      predictedHours,
      statusKey,
      record.notes || null
    );

    return {
      id,
      timestamp,
      createdAt,
      bpm,
      gsr,
      temperature,
      humidity,
      hoursSinceHydration: predictedHours,
      predictedHoursSinceHydration: predictedHours,
      statusKey,
      notes: record.notes || null
    };
  },

  deleteById(id) {
    const stmt = db.prepare(`DELETE FROM measurements WHERE id = ?`);
    stmt.run(id);
    return true;
  },

  clearAll() {
    db.exec(`DELETE FROM measurements;`);
    return true;
  },

  seedDemoDataIfEmpty() {
    const countStmt = db.prepare(`SELECT COUNT(*) as count FROM measurements`);
    const { count } = countStmt.get();
    if (count > 0) return;

    const now = Date.now();
    for (let i = 12; i >= 0; i--) {
      const hoursAgo = i;
      const hoursPredicted = Math.max(0.5, (12 - i) * 1.1).toFixed(1);
      const bpm = Math.round(72 + Math.sin(i) * 6 + (hoursPredicted > 10 ? 12 : 0));
      const gsr = +(5.5 + Math.cos(i) * 1.2 - (hoursPredicted > 10 ? 2.5 : 0)).toFixed(2);
      const temperature = +(36.5 + (hoursPredicted > 10 ? 0.4 : 0) + Math.random() * 0.2).toFixed(1);
      const humidity = +(55 + Math.sin(i) * 5).toFixed(1);

      this.insert({
        id: `sample_${i}`,
        timestamp: now - hoursAgo * 3600 * 1000,
        bpm,
        gsr,
        temperature,
        humidity,
        predictedHoursSinceHydration: parseFloat(hoursPredicted),
        statusKey: parseFloat(hoursPredicted) > 10 ? 'AT_RISK' : 'WELL_HYDRATED',
        notes: 'Initial synthetic seed calibration'
      });
    }
  }
};
