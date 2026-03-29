/**
 * Meal type definitions with time-based auto-selection ranges.
 * Time ranges from BR-CTX-01.
 */

export const MEAL_TYPES = [
  { id: 'breakfast', label: 'Breakfast' },
  { id: 'brunch', label: 'Brunch' },
  { id: 'lunch', label: 'Lunch' },
  { id: 'snack', label: 'Snack' },
  { id: 'dinner', label: 'Dinner' },
  { id: 'dessert', label: 'Dessert' },
];

/**
 * Time ranges for auto-selecting meal type based on device local time.
 * Each entry: [startHour, endHour, mealTypeId]
 * Hours are in 24h format. Ranges are [start, end).
 */
export const MEAL_TIME_RANGES = [
  [5, 10, 'breakfast'],
  [10, 11.5, 'brunch'],
  [11.5, 14, 'lunch'],
  [14, 17, 'snack'],
  [17, 21, 'dinner'],
  [21, 24, 'snack'],
  [0, 5, 'snack'],
];

export const DEFAULT_MEAL_TYPE = 'dinner';
