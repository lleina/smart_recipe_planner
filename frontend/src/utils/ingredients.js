/**
 * Ingredient parsing and scaling utilities.
 */

import { VLM_CONFIDENCE_THRESHOLD, VLM_AUTO_CONFIRM_THRESHOLD, PERISHABLE_URGENCY_DAYS } from '../constants/config';

/**
 * Filters VLM-identified ingredients by confidence threshold.
 * @param {Array} ingredients - Raw VLM ingredient list.
 * @returns {Array} Filtered ingredients with confidence >= threshold.
 */
export const filterByConfidence = (ingredients) => {
  if (!Array.isArray(ingredients)) return [];
  return ingredients.filter((i) => i.confidence >= VLM_CONFIDENCE_THRESHOLD);
};

/**
 * Determines if an ingredient should be auto-confirmed.
 * @param {object} ingredient - Ingredient with confidence score.
 * @returns {boolean} True if confidence >= auto-confirm threshold.
 */
export const shouldAutoConfirm = (ingredient) => {
  return ingredient?.confidence >= VLM_AUTO_CONFIRM_THRESHOLD;
};

/**
 * Checks if an ingredient is flagged as "use soon" (high urgency).
 * @param {object} ingredient - Ingredient with urgency field.
 * @returns {boolean} True if perishable and urgency <= threshold days.
 */
export const isUseSoon = (ingredient) => {
  if (!ingredient || ingredient.category !== 'perishable') return false;
  return typeof ingredient.urgency === 'number' && ingredient.urgency <= PERISHABLE_URGENCY_DAYS;
};

/**
 * Scales ingredient quantity by serving ratio.
 * @param {number} quantity - Original quantity.
 * @param {number} originalServings - Original serving count.
 * @param {number} newServings - Target serving count.
 * @returns {number} Scaled quantity, rounded to 2 decimal places.
 */
export const scaleQuantity = (quantity, originalServings, newServings) => {
  if (!originalServings || !newServings || !quantity) return quantity || 0;
  const scaled = (quantity / originalServings) * newServings;
  return Math.round(scaled * 100) / 100;
};

/**
 * Creates a default manually-added ingredient.
 * @param {string} name - Ingredient name.
 * @returns {object} Ingredient with default values per spec.
 */
export const createManualIngredient = (name) => ({
  name: name.trim().toLowerCase(),
  confidence: 1.0,
  category: 'shelf-stable',
  urgency: null,
  estimatedQuantity: 1,
  unit: 'pieces',
  confirmed: true,
});

/**
 * Deduplicates ingredients by name (case-insensitive).
 * When duplicates are found, keeps the entry with the highest confidence
 * and averages the estimatedQuantity across all duplicates.
 * @param {Array} ingredients - Ingredient list (may contain duplicates).
 * @returns {Array} Deduplicated ingredient list.
 */
export const deduplicateIngredients = (ingredients) => {
  if (!Array.isArray(ingredients)) return [];
  const seen = {};
  const quantities = {};
  for (const item of ingredients) {
    const key = (item.name || '').toLowerCase().trim();
    if (!seen[key] || item.confidence > seen[key].confidence) {
      seen[key] = item;
    }
    if (!quantities[key]) quantities[key] = [];
    quantities[key].push(item.estimatedQuantity ?? 1);
  }
  return Object.keys(seen).map((key) => {
    const qty = quantities[key];
    const avg = qty.reduce((a, b) => a + b, 0) / qty.length;
    return { ...seen[key], estimatedQuantity: Math.round(avg * 100) / 100 };
  });
};

/**
 * Sorts ingredients by urgency (most urgent first), then by category.
 * @param {Array} ingredients - Ingredient list.
 * @returns {Array} Sorted copy of the list.
 */
export const sortByUrgency = (ingredients) => {
  if (!Array.isArray(ingredients)) return [];
  return [...ingredients].sort((a, b) => {
    const urgA = a.urgency ?? Infinity;
    const urgB = b.urgency ?? Infinity;
    return urgA - urgB;
  });
};
