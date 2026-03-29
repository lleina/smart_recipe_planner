/**
 * Tests for ingredient utility functions.
 */

import {
  filterByConfidence,
  shouldAutoConfirm,
  isUseSoon,
  scaleQuantity,
  createManualIngredient,
  sortByUrgency,
} from '../../src/utils/ingredients';

const mockIngredients = [
  { name: 'spinach', confidence: 0.93, category: 'perishable', urgency: 2, estimatedQuantity: 1, unit: 'bag' },
  { name: 'tomato', confidence: 0.95, category: 'perishable', urgency: 5, estimatedQuantity: 4, unit: 'pieces' },
  { name: 'salt', confidence: 0.4, category: 'shelf-stable', urgency: null, estimatedQuantity: 1, unit: 'container' },
  { name: 'onion', confidence: 0.88, category: 'semi-perishable', urgency: 14, estimatedQuantity: 2, unit: 'pieces' },
  { name: 'pasta', confidence: 0.80, category: 'shelf-stable', urgency: null, estimatedQuantity: 1, unit: 'box' },
];

describe('filterByConfidence', () => {
  test('removes ingredients below 0.5 confidence', () => {
    const result = filterByConfidence(mockIngredients);
    expect(result).toHaveLength(4);
    expect(result.find((i) => i.name === 'salt')).toBeUndefined();
  });

  test('returns empty array for invalid input', () => {
    expect(filterByConfidence(null)).toEqual([]);
    expect(filterByConfidence('not-array')).toEqual([]);
  });
});

describe('shouldAutoConfirm', () => {
  test('returns true for confidence >= 0.8', () => {
    expect(shouldAutoConfirm({ confidence: 0.93 })).toBe(true);
    expect(shouldAutoConfirm({ confidence: 0.80 })).toBe(true);
  });

  test('returns false for confidence < 0.8', () => {
    expect(shouldAutoConfirm({ confidence: 0.79 })).toBe(false);
    expect(shouldAutoConfirm({ confidence: 0.4 })).toBe(false);
  });

  test('returns false for invalid input', () => {
    expect(shouldAutoConfirm(null)).toBe(false);
    expect(shouldAutoConfirm({})).toBe(false);
  });
});

describe('isUseSoon', () => {
  test('flags perishable items with urgency <= 3 days', () => {
    expect(isUseSoon({ category: 'perishable', urgency: 2 })).toBe(true);
    expect(isUseSoon({ category: 'perishable', urgency: 3 })).toBe(true);
  });

  test('does not flag perishable items with urgency > 3 days', () => {
    expect(isUseSoon({ category: 'perishable', urgency: 5 })).toBe(false);
  });

  test('does not flag non-perishable items', () => {
    expect(isUseSoon({ category: 'shelf-stable', urgency: 1 })).toBe(false);
    expect(isUseSoon({ category: 'semi-perishable', urgency: 2 })).toBe(false);
  });

  test('handles null/undefined', () => {
    expect(isUseSoon(null)).toBe(false);
    expect(isUseSoon({ category: 'perishable', urgency: null })).toBe(false);
  });
});

describe('scaleQuantity', () => {
  test('scales correctly', () => {
    expect(scaleQuantity(2, 4, 8)).toBe(4);
    expect(scaleQuantity(1, 2, 6)).toBe(3);
    expect(scaleQuantity(3, 4, 2)).toBe(1.5);
  });

  test('handles edge cases', () => {
    expect(scaleQuantity(0, 4, 8)).toBe(0);
    expect(scaleQuantity(2, 0, 4)).toBe(2);
    expect(scaleQuantity(null, 4, 8)).toBe(0);
  });
});

describe('createManualIngredient', () => {
  test('creates ingredient with default values per spec', () => {
    const result = createManualIngredient('  Chicken Breast  ');
    expect(result).toEqual({
      name: 'chicken breast',
      confidence: 1.0,
      category: 'shelf-stable',
      urgency: null,
      estimatedQuantity: 1,
      unit: 'pieces',
      confirmed: true,
    });
  });
});

describe('sortByUrgency', () => {
  test('sorts most urgent first', () => {
    const result = sortByUrgency(mockIngredients);
    expect(result[0].name).toBe('spinach');
    expect(result[1].name).toBe('tomato');
    expect(result[2].name).toBe('onion');
  });

  test('puts null urgency items last', () => {
    const result = sortByUrgency(mockIngredients);
    const lastTwo = result.slice(-2).map((i) => i.name);
    expect(lastTwo).toContain('salt');
    expect(lastTwo).toContain('pasta');
  });

  test('handles invalid input', () => {
    expect(sortByUrgency(null)).toEqual([]);
  });
});
