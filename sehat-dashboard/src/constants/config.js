/**
 * SEHAT System Constants & Configurations
 * Centralized source of truth for hydration logic and sensor boundaries.
 */

// Hydration classification rules
export const HYDRATION_RULES = {
  // Hours threshold: > 10 is 'In Risk of Dehydration', <= 10 is 'Well Hydrated'
  DEHYDRATION_HOURS_THRESHOLD: 10,
  
  STATUS: {
    WELL_HYDRATED: {
      key: 'WELL_HYDRATED',
      label: 'Well Hydrated',
      color: 'emerald',
      description: 'Fluid levels are in optimal physiological balance.',
      suggestion: 'Tubuh Anda sudah terhidrasi dengan baik. Tidak perlu minum secara berlebihan saat ini—cukup minum air putih secara berkala untuk menjaga keseimbangan cairan tubuh.',
    },
    AT_RISK: {
      key: 'AT_RISK',
      label: 'In Risk of Dehydration',
      color: 'rose',
      description: 'Prolonged period without hydration detected. Please rehydrate immediately.',
      suggestion: 'Tindakan Diperlukan: Segera minum 250–500 mL air putih atau cairan elektrolit, hindari aktivitas fisik berat untuk sementara, dan lakukan pengukuran ulang dalam 30–60 menit.',
    }
  }
};

// Sensor physiological normal reference ranges
export const SENSOR_RANGES = {
  BPM: { min: 60, max: 100, unit: 'BPM', label: 'Heart Rate (PPG)' },
  SPO2: { min: 95, max: 100, unit: '%', label: 'Oxygen Saturation (SpO₂)' },
  GSR: { min: 2.0, max: 20.0, unit: 'μS', label: 'Skin Conductance (GSR)' }
};

// Local storage key for persistent history
export const STORAGE_KEYS = {
  MEASUREMENT_HISTORY: 'sehat_measurement_history_v1',
  DEVICE_SETTINGS: 'sehat_device_settings_v1'
};
