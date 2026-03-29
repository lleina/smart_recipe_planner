/**
 * Tests for time utility functions.
 */

import { getMealTypeByTime, formatMinutes, getDefaultTimeByPreference } from '../../src/utils/time';

describe('getMealTypeByTime', () => {
  const makeDate = (hours, minutes = 0) => {
    const d = new Date(2026, 2, 28);
    d.setHours(hours, minutes, 0, 0);
    return d;
  };

  test('returns breakfast for 5:00-10:00', () => {
    expect(getMealTypeByTime(makeDate(5, 0))).toBe('breakfast');
    expect(getMealTypeByTime(makeDate(7, 30))).toBe('breakfast');
    expect(getMealTypeByTime(makeDate(9, 59))).toBe('breakfast');
  });

  test('returns brunch for 10:00-11:30', () => {
    expect(getMealTypeByTime(makeDate(10, 0))).toBe('brunch');
    expect(getMealTypeByTime(makeDate(11, 0))).toBe('brunch');
    expect(getMealTypeByTime(makeDate(11, 29))).toBe('brunch');
  });

  test('returns lunch for 11:30-14:00', () => {
    expect(getMealTypeByTime(makeDate(11, 30))).toBe('lunch');
    expect(getMealTypeByTime(makeDate(12, 0))).toBe('lunch');
    expect(getMealTypeByTime(makeDate(13, 59))).toBe('lunch');
  });

  test('returns snack for 14:00-17:00', () => {
    expect(getMealTypeByTime(makeDate(14, 0))).toBe('snack');
    expect(getMealTypeByTime(makeDate(16, 30))).toBe('snack');
  });

  test('returns dinner for 17:00-21:00', () => {
    expect(getMealTypeByTime(makeDate(17, 0))).toBe('dinner');
    expect(getMealTypeByTime(makeDate(19, 0))).toBe('dinner');
    expect(getMealTypeByTime(makeDate(20, 59))).toBe('dinner');
  });

  test('returns snack for 21:00-5:00', () => {
    expect(getMealTypeByTime(makeDate(21, 0))).toBe('snack');
    expect(getMealTypeByTime(makeDate(23, 30))).toBe('snack');
    expect(getMealTypeByTime(makeDate(2, 0))).toBe('snack');
    expect(getMealTypeByTime(makeDate(4, 59))).toBe('snack');
  });

  test('defaults to current time when no date provided', () => {
    const result = getMealTypeByTime();
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('formatMinutes', () => {
  test('formats minutes only', () => {
    expect(formatMinutes(45)).toBe('45m');
    expect(formatMinutes(5)).toBe('5m');
  });

  test('formats hours only', () => {
    expect(formatMinutes(60)).toBe('1h');
    expect(formatMinutes(120)).toBe('2h');
  });

  test('formats hours and minutes', () => {
    expect(formatMinutes(75)).toBe('1h 15m');
    expect(formatMinutes(90)).toBe('1h 30m');
  });

  test('handles zero', () => {
    expect(formatMinutes(0)).toBe('0m');
  });

  test('handles invalid input', () => {
    expect(formatMinutes(-10)).toBe('0m');
    expect(formatMinutes(NaN)).toBe('0m');
    expect(formatMinutes(null)).toBe('0m');
    expect(formatMinutes(undefined)).toBe('0m');
  });
});

describe('getDefaultTimeByPreference', () => {
  test('returns correct defaults', () => {
    expect(getDefaultTimeByPreference('quick')).toBe(15);
    expect(getDefaultTimeByPreference('moderate')).toBe(30);
    expect(getDefaultTimeByPreference('extended')).toBe(60);
  });

  test('defaults to moderate for unknown input', () => {
    expect(getDefaultTimeByPreference('unknown')).toBe(30);
    expect(getDefaultTimeByPreference(null)).toBe(30);
  });
});
