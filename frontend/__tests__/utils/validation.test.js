/**
 * Tests for validation utility functions.
 */

import {
  isValidServingCount,
  clampServingCount,
  isValidCookingTime,
  validateImageFile,
  sanitizeInput,
  isValidEmail,
} from '../../src/utils/validation';

describe('isValidServingCount', () => {
  test('accepts valid counts', () => {
    expect(isValidServingCount(1)).toBe(true);
    expect(isValidServingCount(6)).toBe(true);
    expect(isValidServingCount(12)).toBe(true);
  });

  test('rejects out-of-range counts', () => {
    expect(isValidServingCount(0)).toBe(false);
    expect(isValidServingCount(13)).toBe(false);
    expect(isValidServingCount(-1)).toBe(false);
  });

  test('rejects non-integers', () => {
    expect(isValidServingCount(2.5)).toBe(false);
    expect(isValidServingCount(NaN)).toBe(false);
  });
});

describe('clampServingCount', () => {
  test('clamps to range', () => {
    expect(clampServingCount(0)).toBe(1);
    expect(clampServingCount(15)).toBe(12);
    expect(clampServingCount(6)).toBe(6);
  });

  test('handles non-numeric input', () => {
    expect(clampServingCount('abc')).toBe(1);
    expect(clampServingCount(null)).toBe(1);
  });
});

describe('isValidCookingTime', () => {
  test('accepts valid times', () => {
    expect(isValidCookingTime(5)).toBe(true);
    expect(isValidCookingTime(60)).toBe(true);
    expect(isValidCookingTime(120)).toBe(true);
  });

  test('rejects out-of-range times', () => {
    expect(isValidCookingTime(4)).toBe(false);
    expect(isValidCookingTime(121)).toBe(false);
    expect(isValidCookingTime(-1)).toBe(false);
  });
});

describe('validateImageFile', () => {
  test('accepts valid files with type field', () => {
    const file = { uri: 'file://photo.jpg', type: 'image/jpeg', fileSize: 1000000 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('accepts valid files with mimeType field (Expo ImagePicker format)', () => {
    const file = { uri: 'file://photo.jpg', mimeType: 'image/jpeg', fileSize: 1000000 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('accepts PNG via mimeType', () => {
    const file = { uri: 'file://image.png', mimeType: 'image/png', fileSize: 2000000 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('accepts HEIC via type field', () => {
    const file = { uri: 'file://photo.heic', type: 'image/heic', fileSize: 3000000 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('accepts files without mimeType or type (Android edge case)', () => {
    const file = { uri: 'file://photo.jpg', fileSize: 1000000 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('accepts files without fileSize (backwards compatibility)', () => {
    const file = { uri: 'file://photo.jpg', mimeType: 'image/jpeg' };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('rejects missing file', () => {
    expect(validateImageFile(null).valid).toBe(false);
    expect(validateImageFile({}).valid).toBe(false);
  });

  test('rejects file without URI', () => {
    const file = { mimeType: 'image/jpeg', fileSize: 1000 };
    expect(validateImageFile(file).valid).toBe(false);
    expect(validateImageFile(file).error).toContain('No file selected');
  });

  test('rejects oversized files', () => {
    const file = { uri: 'file://big.jpg', mimeType: 'image/jpeg', fileSize: 6000000 };
    expect(validateImageFile(file).valid).toBe(false);
    expect(validateImageFile(file).error).toContain('5MB');
  });

  test('rejects exactly over 5MB limit', () => {
    const file = { uri: 'file://big.jpg', mimeType: 'image/jpeg', fileSize: 5242881 };
    expect(validateImageFile(file).valid).toBe(false);
  });

  test('accepts file at 5MB limit', () => {
    const file = { uri: 'file://photo.jpg', mimeType: 'image/jpeg', fileSize: 5242880 };
    expect(validateImageFile(file)).toEqual({ valid: true, error: null });
  });

  test('rejects invalid MIME types via mimeType field', () => {
    const file = { uri: 'file://doc.pdf', mimeType: 'application/pdf', fileSize: 1000 };
    expect(validateImageFile(file).valid).toBe(false);
    expect(validateImageFile(file).error).toContain('JPEG, PNG, and HEIC');
  });

  test('rejects invalid MIME types via type field', () => {
    const file = { uri: 'file://video.mp4', type: 'video/mp4', fileSize: 1000 };
    expect(validateImageFile(file).valid).toBe(false);
  });

  test('rejects GIF (not in allowed types)', () => {
    const file = { uri: 'file://animated.gif', mimeType: 'image/gif', fileSize: 1000 };
    expect(validateImageFile(file).valid).toBe(false);
  });
});

describe('sanitizeInput', () => {
  test('strips HTML tags', () => {
    expect(sanitizeInput('<script>alert("xss")</script>hello')).toBe('hello');
    expect(sanitizeInput('normal text')).toBe('normal text');
  });

  test('trims whitespace', () => {
    expect(sanitizeInput('  hello  ')).toBe('hello');
  });

  test('handles non-string input', () => {
    expect(sanitizeInput(null)).toBe('');
    expect(sanitizeInput(123)).toBe('');
  });
});

describe('isValidEmail', () => {
  test('accepts valid emails', () => {
    expect(isValidEmail('user@example.com')).toBe(true);
    expect(isValidEmail('a.b@c.co')).toBe(true);
  });

  test('rejects invalid emails', () => {
    expect(isValidEmail('not-an-email')).toBe(false);
    expect(isValidEmail('@no-local.com')).toBe(false);
    expect(isValidEmail('no-domain@')).toBe(false);
    expect(isValidEmail('')).toBe(false);
    expect(isValidEmail(null)).toBe(false);
  });
});
