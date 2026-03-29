/**
 * Application configuration constants.
 * API keys and secrets are loaded from environment variables only.
 */

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || 'http://localhost:8000/api';
export const API_TIMEOUT_MS = 30000;
export const VLM_TIMEOUT_MS = 120000;

export const IMAGE_MAX_SIZE_BYTES = 5 * 1024 * 1024;
export const IMAGE_COMPRESSION_QUALITY = 0.7;
export const IMAGE_MAX_COMPRESSED_BYTES = 1024 * 1024;
export const IMAGE_MAX_DIMENSION = 1536;
export const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/heic'];

export const VLM_CONFIDENCE_THRESHOLD = 0.5;
export const VLM_AUTO_CONFIRM_THRESHOLD = 0.8;
export const PERISHABLE_URGENCY_DAYS = 3;

export const RECIPE_BATCH_SIZE = 5;
export const RECIPE_POOL_SIZE = 40;
export const REFETCH_THRESHOLD = 10;

export const SERVING_COUNT_MIN = 1;
export const SERVING_COUNT_MAX = 12;
export const SERVING_COUNT_DEFAULT = 1;

export const COOKING_TIME_MIN = 5;
export const COOKING_TIME_MAX = 120;

export const JWT_ACCESS_TOKEN_EXPIRY_MIN = 15;
export const JWT_REFRESH_TOKEN_EXPIRY_DAYS = 30;

export const OFFLINE_EVENT_QUEUE_MAX = 500;

export const FEATURE_FLAGS = {
  enableVlm: true,
  enableMockData: process.env.EXPO_PUBLIC_ENABLE_MOCK_DATA === 'true',
};
