/**
 * SEHAT History Service (Storage Abstraction Layer)
 * 
 * Future Development Note:
 * If migrating to a real database (SQLite, PostgreSQL, Supabase, Firebase, or an ESP32 backend API),
 * you only need to change the implementation within this file.
 */
import { STORAGE_KEYS } from '../constants/config';

export const HistoryService = {
  /**
   * Retrieves all saved measurement records.
   * @returns {Array<object>} List of measurement records (newest first)
   */
  getAll() {
    try {
      const data = localStorage.getItem(STORAGE_KEYS.MEASUREMENT_HISTORY);
      if (!data) return [];
      const parsed = JSON.parse(data);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      console.error('Failed to read measurement history from local storage:', err);
      return [];
    }
  },

  /**
   * Saves a new measurement record.
   * @param {object} record - Telemetry reading
   * @returns {Array<object>} The updated list of records
   */
  save(record) {
    try {
      const current = this.getAll();
      // Ensure record has unique ID and timestamp
      const newEntry = {
        id: record.id || `rec_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
        timestamp: record.timestamp || Date.now(),
        bpm: Number(record.bpm),
        gsr: Number(record.gsr),
        temperature: Number(record.temperature),
        humidity: Number(record.humidity),
        hoursSinceHydration: Number(record.hoursSinceHydration),
        statusKey: record.hoursSinceHydration > 10 ? 'AT_RISK' : 'WELL_HYDRATED',
      };

      // Keep up to 200 most recent records to prevent unbounded browser memory usage
      const updated = [newEntry, ...current].slice(0, 200);
      localStorage.setItem(STORAGE_KEYS.MEASUREMENT_HISTORY, JSON.stringify(updated));
      return updated;
    } catch (err) {
      console.error('Failed to save measurement record:', err);
      return this.getAll();
    }
  },

  /**
   * Clears all measurement history.
   */
  clear() {
    try {
      localStorage.removeItem(STORAGE_KEYS.MEASUREMENT_HISTORY);
      return [];
    } catch (err) {
      console.error('Failed to clear measurement history:', err);
      return [];
    }
  },

  /**
   * Seeds realistic demo telemetry history if empty.
   */
  seedSampleDataIfEmpty() {
    const existing = this.getAll();
    if (existing.length > 0) return existing;

    const sampleData = [];
    const now = Date.now();
    
    // Generate 12 sample points across the last 12 hours
    for (let i = 12; i >= 0; i--) {
      const hoursAgo = i;
      const hoursSinceHydration = Math.max(0.5, (12 - i) * 1.1).toFixed(1);
      const bpm = Math.round(72 + Math.sin(i) * 6 + (hoursSinceHydration > 10 ? 12 : 0));
      const gsr = +(5.5 + Math.cos(i) * 1.2 - (hoursSinceHydration > 10 ? 2.5 : 0)).toFixed(2);
      const temperature = +(36.5 + (hoursSinceHydration > 10 ? 0.4 : 0) + Math.random() * 0.2).toFixed(1);
      const humidity = +(55 + Math.sin(i) * 5).toFixed(1);

      sampleData.push({
        id: `sample_${i}`,
        timestamp: now - hoursAgo * 3600 * 1000,
        bpm,
        gsr,
        temperature,
        humidity,
        hoursSinceHydration: parseFloat(hoursSinceHydration),
        statusKey: parseFloat(hoursSinceHydration) > 10 ? 'AT_RISK' : 'WELL_HYDRATED',
      });
    }

    try {
      localStorage.setItem(STORAGE_KEYS.MEASUREMENT_HISTORY, JSON.stringify(sampleData));
    } catch (e) {
      console.error('Error seeding demo data:', e);
    }
    return sampleData;
  }
};
