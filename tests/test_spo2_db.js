import assert from 'node:assert/strict';

process.env.SEHAT_DB_PATH = ':memory:';
const { MeasurementRepository } = await import('../server/db.js');

const base = { bpm: 72, gsr: 6.4 };
const valid = MeasurementRepository.insert({ ...base, spo2: 98, spo2Valid: true });
assert.equal(valid.spo2, 98);
assert.equal(valid.spo2Valid, 1);
assert.equal(MeasurementRepository.getLatest().spo2, 98);

const invalid = MeasurementRepository.insert({ ...base, spo2: 101, spo2Valid: true });
assert.equal(invalid.spo2, null);
assert.equal(invalid.spo2Valid, 0);
assert.equal(MeasurementRepository.getLatest().spo2, null);

const missing = MeasurementRepository.insert(base);
assert.equal(missing.spo2, null);
assert.equal(missing.spo2Valid, 0);
console.log('SpO2 database checks passed');
