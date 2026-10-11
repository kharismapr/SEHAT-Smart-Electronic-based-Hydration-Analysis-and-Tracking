/**
 * SEHAT History Service (Storage & API Abstraction Layer)
 * 
 * Manages synchronization between SQLite Backend (http://localhost:5000/api/measurements)
 * and LocalStorage fallback.
 */
import { STORAGE_KEYS } from '../constants/config';

const API_BASE_URL = 'http://localhost:5000/api';

export const HistoryService = {
  /**
   * Retrieves all saved measurement records from local cache.
   * @returns {Array<object>} List of measurement records (newest first)
   */
  getAllLocal() {
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
   * Synchronous accessor for initial UI render
   */
  getAll() {
    return this.getAllLocal();
  },

  /**
   * Fetches latest measurements from SQLite Backend API, falls back to LocalStorage.
   * @returns {Promise<Array<object>>}
   */
  async fetchAllRemote() {
    try {
      const response = await fetch(`${API_BASE_URL}/measurements?limit=200`, {
        signal: AbortSignal.timeout(2000)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (result.success && Array.isArray(result.data)) {
        // Cache to local storage
        localStorage.setItem(STORAGE_KEYS.MEASUREMENT_HISTORY, JSON.stringify(result.data));
        return result.data;
      }
    } catch (err) {
      console.warn('Backend server not reachable, using local storage cache:', err.message);
    }
    return this.getAllLocal();
  },

  /**
   * Saves a new measurement record both locally and to SQLite backend.
   * @param {object} record - Telemetry reading
   * @returns {Array<object>} The updated list of records
   */
  save(record) {
    try {
      const current = this.getAllLocal();
      const newEntry = {
        id: record.id || `meas_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
        timestamp: record.timestamp || Date.now(),
        bpm: Number(record.bpm),
        gsr: Number(record.gsr),
        temperature: Number(record.temperature),
        humidity: Number(record.humidity),
        hoursSinceHydration: Number(record.hoursSinceHydration),
        predictedHoursSinceHydration: Number(record.hoursSinceHydration),
        statusKey: record.statusKey || (Number(record.hoursSinceHydration) > 10 ? 'AT_RISK' : 'WELL_HYDRATED'),
        notes: record.notes || null
      };

      // 1. Update local cache immediately
      const updated = [newEntry, ...current].slice(0, 200);
      localStorage.setItem(STORAGE_KEYS.MEASUREMENT_HISTORY, JSON.stringify(updated));

      // 2. Fire and forget sync to SQLite backend
      fetch(`${API_BASE_URL}/measurements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newEntry)
      }).catch(err => {
        console.warn('Could not sync measurement to SQLite backend:', err.message);
      });

      return updated;
    } catch (err) {
      console.error('Failed to save measurement record:', err);
      return this.getAllLocal();
    }
  },

  /**
   * Clears all measurement history locally and in SQLite backend.
   */
  clear() {
    try {
      localStorage.removeItem(STORAGE_KEYS.MEASUREMENT_HISTORY);

      fetch(`${API_BASE_URL}/measurements`, {
        method: 'DELETE'
      }).catch(err => {
        console.warn('Could not clear remote measurements on SQLite backend:', err.message);
      });

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
    const existing = this.getAllLocal();
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
        predictedHoursSinceHydration: parseFloat(hoursSinceHydration),
        statusKey: parseFloat(hoursSinceHydration) > 10 ? 'AT_RISK' : 'WELL_HYDRATED',
        notes: 'Initial synthetic seed calibration'
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
