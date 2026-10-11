/**
 * SEHAT Pure Calculation, Regression & Formatting Utilities
 * Isolated, testable pure functions.
 */
import { HYDRATION_RULES } from '../constants/config';

/**
 * SEHAT Physiological Regression Model (Empirical / Model Simulator)
 * 
 * Maps raw sensor features -> estimated hours since hydration (Regression output):
 * f(PPG, GSR, Temperature, Humidity) -> Estimated Hours (y_hat)
 * 
 * Future Development:
 * When integrating trained ML model coefficients or an ONNX/TensorFlow.js model,
 * replace this calculation function with your model weights.
 *
 * @param {object} params
 * @param {number} params.bpm - Heart rate in beats per minute
 * @param {number} params.gsr - Galvanic skin response / conductance in μS
 * @param {number} params.temperature - Skin/body temperature in °C
 * @param {number} params.humidity - Ambient relative humidity in %
 * @returns {number} Estimated hours since hydration (Regression result)
 */
export function estimateHoursSinceHydration({ bpm = 72, gsr = 8.0, temperature = 36.6, humidity = 55 }) {
  // Biological heuristics:
  // 1. Lower GSR (reduced perspiration/conductance) strongly indicates longer dry interval
  // 2. Elevated resting heart rate (PPG) is a common compensation mechanism for blood volume loss
  // 3. Elevated skin/core temperature and lower humidity accelerate fluid depletion
  const baselineGsr = 14.0; // Well-hydrated baseline conductance
  const gsrDeficit = Math.max(0, (baselineGsr - gsr) * 0.95);
  
  const baselineBpm = 68;
  const bpmDeficit = Math.max(0, (bpm - baselineBpm) * 0.09);
  
  const baselineTemp = 36.4;
  const tempDeficit = Math.max(0, (temperature - baselineTemp) * 1.6);
  
  const humidityCorrection = Math.max(0, (50 - humidity) * 0.03);

  const rawEstimate = gsrDeficit + bpmDeficit + tempDeficit + humidityCorrection;
  
  // Bound prediction between 0.1 and 24.0 hours
  const boundedEstimate = Math.max(0.2, Math.min(24.0, rawEstimate));
  return parseFloat(boundedEstimate.toFixed(1));
}

/**
 * Classifies hydration status given the regression output (hours since hydration).
 * @param {number} hours - Inferred regression hours
 * @returns {object} The status configuration object
 */
export function classifyHydration(hours) {
  const numHours = parseFloat(hours) || 0;
  if (numHours > HYDRATION_RULES.DEHYDRATION_HOURS_THRESHOLD) {
    return HYDRATION_RULES.STATUS.AT_RISK;
  }
  return HYDRATION_RULES.STATUS.WELL_HYDRATED;
}

/**
 * Formats a timestamp into human-readable date & time.
 */
export function formatDateTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
}

/**
 * Formats a timestamp into a short time string for charts.
 */
export function formatTimeOnly(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
}

/**
 * Converts an array of telemetry records into a downloadable CSV string.
 */
export function exportToCSVString(records) {
  if (!records || records.length === 0) return '';
  
  const headers = [
    'Timestamp',
    'Date & Time',
    'PPG (BPM)',
    'GSR (uS)',
    'Temperature (C)',
    'Humidity (%)',
    'Inferred Hours Dry (Regression)',
    'Classification'
  ];
  
  const rows = records.map(r => [
    r.timestamp,
    `"${new Date(r.timestamp).toISOString()}"`,
    r.bpm,
    r.gsr,
    r.temperature,
    r.humidity,
    r.hoursSinceHydration,
    `"${r.statusKey === 'AT_RISK' ? 'In Risk of Dehydration' : 'Well Hydrated'}"`
  ]);

  return [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
}
