import express from 'express';
import cors from 'cors';
import { spawn, execFile } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MeasurementRepository } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BRIDGE_SCRIPT_PATH = path.resolve(__dirname, '..', 'scripts', 'serial_bridge.py');

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
  timestamp: 0
};

// Device Command Queue (e.g. 'c' = calibrate, 's' = start, 'f' = flush, 'r' = reset)
let pendingCommands = [];

// ============================================================================
// Managed Serial Bridge Process & CLI Serial Monitor Log Buffer
// ============================================================================
let bridgeProcess = null;
let bridgePortArg = null;
let bridgeLogs = [];
const MAX_BRIDGE_LOGS = 400;

function appendBridgeLog(text, level = 'info') {
  const lines = String(text).split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line) continue;
    bridgeLogs.push({
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      timestamp: Date.now(),
      text: line,
      level
    });
  }
  if (bridgeLogs.length > MAX_BRIDGE_LOGS) {
    bridgeLogs = bridgeLogs.slice(-MAX_BRIDGE_LOGS);
  }
}

function startSerialBridge(port = '') {
  if (bridgeProcess && bridgeProcess.exitCode === null && !bridgeProcess.killed) {
    return {
      alreadyRunning: true,
      pid: bridgeProcess.pid,
      port: bridgePortArg || 'Auto'
    };
  }

  const cleanPort = typeof port === 'string' ? port.trim() : '';
  bridgePortArg = cleanPort || null;

  const args = ['-u', BRIDGE_SCRIPT_PATH];
  if (cleanPort) {
    args.push(cleanPort);
  }

  appendBridgeLog(
    `[Dashboard] Launching serial_bridge.py (${cleanPort ? `Port: ${cleanPort}` : 'Auto-detect COM port'})...`,
    'system'
  );

  try {
    const child = spawn('python', args, {
      cwd: path.resolve(__dirname, '..'),
      windowsHide: true
    });

    bridgeProcess = child;

    child.stdout.on('data', (chunk) => {
      appendBridgeLog(chunk.toString(), 'stdout');
    });

    child.stderr.on('data', (chunk) => {
      appendBridgeLog(chunk.toString(), 'stderr');
    });

    child.on('error', (err) => {
      appendBridgeLog(`[Process Error] Failed to spawn python serial_bridge.py: ${err.message}`, 'error');
      if (bridgeProcess === child) {
        bridgeProcess = null;
        liveTelemetry.timestamp = 0;
        liveTelemetry.isLive = false;
      }
    });

    child.on('close', (code, signal) => {
      appendBridgeLog(
        `[Bridge Process Exited] code=${code ?? 'null'}${signal ? ` signal=${signal}` : ''}`,
        code === 0 ? 'system' : 'error'
      );
      if (bridgeProcess === child) {
        bridgeProcess = null;
        liveTelemetry.timestamp = 0;
        liveTelemetry.isLive = false;
      }
    });

    return {
      alreadyRunning: false,
      pid: child.pid,
      port: bridgePortArg || 'Auto'
    };
  } catch (err) {
    appendBridgeLog(`[Exception] ${err.message}`, 'error');
    bridgeProcess = null;
    throw err;
  }
}

function stopSerialBridge() {
  if (!bridgeProcess) {
    liveTelemetry.timestamp = 0;
    liveTelemetry.isLive = false;
    return false;
  }
  const pid = bridgeProcess.pid;
  try {
    bridgeProcess.kill();
  } catch {
    // ignore kill error
  }
  bridgeProcess = null;
  bridgePortArg = null;
  liveTelemetry.timestamp = 0;
  liveTelemetry.isLive = false;
  appendBridgeLog(`[Dashboard] Stopped serial_bridge.py (PID ${pid}).`, 'system');
  return true;
}

// Ensure child process is cleaned up when server exits
process.on('exit', () => {
  if (bridgeProcess) {
    try {
      bridgeProcess.kill();
    } catch {
      // ignore
    }
  }
});

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
  const isBridgeActive = liveTelemetry.timestamp > 0 && ageMs < 3500;
  const isBridgeRunning = Boolean(bridgeProcess && bridgeProcess.exitCode === null && !bridgeProcess.killed);
  res.json({
    success: true,
    data: {
      ...liveTelemetry,
      isLive: isBridgeActive,
      bridgeRunning: isBridgeRunning,
      bridgePid: isBridgeRunning ? bridgeProcess.pid : null,
      bridgePort: bridgePortArg || 'Auto'
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

// ============================================================================
// Serial Bridge Control & Serial Monitor Endpoints
// ============================================================================

// GET /api/bridge/status (Returns process state + CLI serial monitor logs)
app.get('/api/bridge/status', (req, res) => {
  const isRunning = Boolean(bridgeProcess && bridgeProcess.exitCode === null && !bridgeProcess.killed);
  const ageMs = Date.now() - liveTelemetry.timestamp;
  const isLive = liveTelemetry.timestamp > 0 && ageMs < 3500;
  res.json({
    success: true,
    data: {
      isRunning,
      isLive,
      pid: isRunning ? bridgeProcess.pid : null,
      port: bridgePortArg || 'Auto',
      logs: bridgeLogs
    }
  });
});

// GET /api/bridge/ports (Lists available serial COM ports via pyserial)
app.get('/api/bridge/ports', (req, res) => {
  const pyCode =
    "import serial.tools.list_ports, json; print(json.dumps([{'port': p.device, 'description': p.description} for p in serial.tools.list_ports.comports()]))";
  execFile('python', ['-c', pyCode], { timeout: 3000, windowsHide: true }, (err, stdout) => {
    if (err) {
      return res.json({ success: true, ports: [] });
    }
    try {
      const ports = JSON.parse(stdout.trim() || '[]');
      res.json({ success: true, ports });
    } catch {
      res.json({ success: true, ports: [] });
    }
  });
});

// POST /api/bridge/start (Spawns python serial_bridge.py from dashboard)
app.post('/api/bridge/start', (req, res) => {
  try {
    const port = req.body?.port || '';
    const info = startSerialBridge(port);
    res.json({
      success: true,
      data: {
        isRunning: true,
        ...info
      }
    });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// POST /api/bridge/stop (Stops the managed serial_bridge.py process)
app.post('/api/bridge/stop', (req, res) => {
  const stopped = stopSerialBridge();
  res.json({
    success: true,
    data: {
      isRunning: false,
      stopped
    }
  });
});

// DELETE /api/bridge/logs (Clears the serial monitor log buffer)
app.delete('/api/bridge/logs', (req, res) => {
  bridgeLogs = [];
  res.json({ success: true });
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
