/**
 * Tests for the base API client.
 */

import { apiRequest, ApiError, setAccessToken, setRefreshTokenHandler } from '../../src/services/api';

// Mock global fetch
global.fetch = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  setAccessToken(null);
  setRefreshTokenHandler(null);
});

describe('apiRequest', () => {
  test('makes GET request with correct URL and headers', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: 'test' }),
    });

    const result = await apiRequest('/test', { method: 'GET' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain('/test');
    expect(options.method).toBe('GET');
    expect(options.headers['Content-Type']).toBe('application/json');
    expect(result).toEqual({ data: 'test' });
  });

  test('includes auth header when token is set', async () => {
    setAccessToken('test-token');
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });

    await apiRequest('/test');

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers['Authorization']).toBe('Bearer test-token');
  });

  test('does not include auth header when skipAuth is true', async () => {
    setAccessToken('test-token');
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });

    await apiRequest('/test', { skipAuth: true });

    const [, options] = global.fetch.mock.calls[0];
    expect(options.headers['Authorization']).toBeUndefined();
  });

  test('throws ApiError on non-2xx response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: { message: 'Not found', code: 'NOT_FOUND', retryable: false } }),
    });

    await expect(apiRequest('/missing')).rejects.toThrow(ApiError);

    try {
      await apiRequest('/missing');
    } catch (err) {
      // Already tested above
    }
  });

  test('throws ApiError with timeout code on abort', async () => {
    global.fetch.mockImplementationOnce(() => {
      const error = new Error('Aborted');
      error.name = 'AbortError';
      return Promise.reject(error);
    });

    await expect(apiRequest('/slow', { timeout: 1 })).rejects.toMatchObject({
      code: 'ERR_TIMEOUT',
      retryable: true,
    });
  });

  test('throws ApiError on network error', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network failure'));

    await expect(apiRequest('/offline')).rejects.toMatchObject({
      code: 'ERR_NETWORK',
      retryable: true,
    });
  });

  test('retries with refreshed token on 401', async () => {
    setAccessToken('expired-token');
    setRefreshTokenHandler(async () => 'new-token');

    global.fetch
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: { message: 'Unauthorized' } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true }),
      });

    const result = await apiRequest('/protected');

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ success: true });
  });
});

describe('ApiError', () => {
  test('has correct properties', () => {
    const err = new ApiError('test message', 'ERR_TEST', 500, true);
    expect(err.message).toBe('test message');
    expect(err.code).toBe('ERR_TEST');
    expect(err.status).toBe(500);
    expect(err.retryable).toBe(true);
    expect(err.name).toBe('ApiError');
    expect(err instanceof Error).toBe(true);
  });
});
