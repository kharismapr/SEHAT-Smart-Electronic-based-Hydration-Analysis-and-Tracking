/**
 * SEHAT USB Serial Bridge (Node.js)
 * 
 * Reads live sensor telemetry and preprocessed window features from ESP32 Serial output
 * and forwards them to the SEHAT backend server (http://localhost:5000/api/measurements).
 * 
 * Usage:
 *   node serial_bridge.js <COM_PORT> (e.g. node serial_bridge.js COM3)
 */

import { createInterface } from 'node:readline';
import { SerialPort } from 'serialport';
import { ReadlineParser } from '@serialport/parser-readline';

const COM_PORT = process.argv[2] || 'COM3';
const BAUD_RATE = 115200;
const SERVER_URL = 'http://localhost:5000/api/measurements';
const LIVE_URL = 'http://localhost:5000/api/telemetry/live';

console.log(`[SEHAT Bridge] Opening ${COM_PORT} at ${BAUD_RATE} baud...`);

let port;
try {
  port = new SerialPort({ path: COM_PORT, baudRate: BAUD_RATE });
} catch (err) {
  console.error(`[Error] Could not open ${COM_PORT}:`, err.message);
  process.exit(1);
}

const parser = port.pipe(new ReadlineParser({ delimiter: '\n' }));

let latestGSR = 9.5;
let latestBPM = 72.0;
let latestSpo2 = null;
let spo2Valid = false;

parser.on('data', async (line) => {
  const text = line.trim();
  console.log(`[ESP32] ${text}`);

  // Unified firmware emits a paired SpO2 value and validity flag.
  const spo2Match = text.match(/SpO2:\s*(null|[\d.]+)\s*(?:%\s*)?\|\s*valid=([01])/);
  if (spo2Match) {
    spo2Valid = spo2Match[2] === '1';
    latestSpo2 = spo2Valid ? Number(spo2Match[1]) : null;
  }
  // Match Heartbeat / BPM from live stream or window summaries
  const bpmMatch = text.match(/(?:BPM|HR|mean_hr)\s*[:=]\s*([\d.]+)/i);
  if (bpmMatch) {
    const hr = parseFloat(bpmMatch[1]);
    if (!isNaN(hr) && hr >= 35 && hr <= 220) {
      latestBPM = hr;
    }
  }

  if (text.startsWith('[Live Stream]') || text.startsWith('LIVE |')) {
    const gsr = text.match(/(?:GSR|GSR_us)\s*[:=]\s*([\d.]+)/i);
    if (gsr) latestGSR = Number(gsr[1]);
    try {
      await fetch(LIVE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bpm: latestBPM,
          spo2: latestSpo2,
          spo2Valid,
          gsr: latestGSR
        })
      });
    } catch (err) {
      console.warn('[Bridge Error] Could not forward live telemetry:', err.message);
    }
  }

  // 1. Match live stream: ADC10=..., GSR_us=...
  const gsrMatch = text.match(/GSR_us=([\d.]+)/);
  if (gsrMatch) {
    latestGSR = parseFloat(gsrMatch[1]);
  }

  // 2. Match PPG window features: mean_hr=..., rmssd=...
  const ppgMatch = text.match(/mean_hr=([\d.]+)/);
  if (ppgMatch) {
    const hr = parseFloat(ppgMatch[1]);
    if (!isNaN(hr) && hr > 30 && hr < 220) {
      latestBPM = hr;
    }
  }

  // 3. Forward complete window feature updates or periodic vitals
  if (text.includes('gsr_mean=') || text.includes('mean_hr=')) {
    try {
      const payload = {
        bpm: latestBPM,
        spo2: latestSpo2,
        spo2Valid,
        gsr: latestGSR,
        notes: 'ESP32 Serial Bridge'
      };

      const res = await fetch(SERVER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        console.log(`[Bridge -> Dashboard] Forwarded telemetry: BPM=${latestBPM}, GSR=${latestGSR} uS`);
      }
    } catch (err) {
      console.warn(`[Bridge Error] Could not forward to server:`, err.message);
    }
  }
});

port.on('open', () => {
  console.log(`[SEHAT Bridge] Connected to ESP32 on ${COM_PORT}! Listening for telemetry...`);
});

port.on('error', (err) => {
  console.error('[SerialPort Error]', err.message);
});
