/**
 * Time-related utility functions.
 * Handles meal type auto-selection and time formatting.
 */

import { MEAL_TIME_RANGES, DEFAULT_MEAL_TYPE } from '../constants/mealTypes';

/**
 * Returns the auto-selected meal type based on the current local hour.
 * @param {Date} [date] - Date to check. Defaults to now.
 * @returns {string} Meal type ID (e.g., 'breakfast', 'dinner').
 */
export const getMealTypeByTime = (date = new Date()) => {
  const hour = date.getHours() + date.getMinutes() / 60;

  for (const [start, end, mealType] of MEAL_TIME_RANGES) {
    if (hour >= start && hour < end) {
      return mealType;
    }
  }

  return DEFAULT_MEAL_TYPE;
};

/**
 * Formats minutes into a human-readable string.
 * @param {number} minutes - Total minutes.
 * @returns {string} Formatted string (e.g., "1h 15m", "45m").
 */
export const formatMinutes = (minutes) => {
  if (!Number.isFinite(minutes) || minutes < 0) return '0m';

  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);

  if (hours === 0) return `${mins}m`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
};

/**
 * Returns the default cooking time in minutes based on time preference.
 * @param {string} timePreference - 'quick' | 'moderate' | 'extended'.
 * @returns {number} Default minutes.
 */
export const getDefaultTimeByPreference = (timePreference) => {
  const defaults = {
    quick: 15,
    moderate: 30,
    extended: 60,
  };
  return defaults[timePreference] || defaults.moderate;
};
