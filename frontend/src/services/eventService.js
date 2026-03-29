/**
 * Behavioral event ingestion service.
 * Sends user interaction events to the backend for recommendation training.
 */

import { post } from './api';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { OFFLINE_EVENT_QUEUE_MAX } from '../constants/config';

const EVENT_QUEUE_KEY = '@event_queue';

/**
 * Sends a behavioral event to the backend.
 * Falls back to local queue if offline.
 * @param {object} event - { userId, sessionId, recipeId, eventType, metadata }
 * @returns {Promise<void>}
 */
export const trackEvent = async (event) => {
  try {
    await post('/events', { ...event, createdAt: new Date().toISOString() });
  } catch {
    await queueEvent(event);
  }
};

/**
 * Queues an event locally when offline.
 * @param {object} event
 */
const queueEvent = async (event) => {
  try {
    const raw = await AsyncStorage.getItem(EVENT_QUEUE_KEY);
    const queue = raw ? JSON.parse(raw) : [];
    if (queue.length >= OFFLINE_EVENT_QUEUE_MAX) return;
    queue.push({ ...event, createdAt: new Date().toISOString() });
    await AsyncStorage.setItem(EVENT_QUEUE_KEY, JSON.stringify(queue));
  } catch {
    // Silently fail - event loss is acceptable over app crash
  }
};

/**
 * Flushes queued events to the backend. Called when connectivity restores.
 * @returns {Promise<number>} Number of events flushed.
 */
export const flushEventQueue = async () => {
  try {
    const raw = await AsyncStorage.getItem(EVENT_QUEUE_KEY);
    const queue = raw ? JSON.parse(raw) : [];
    if (queue.length === 0) return 0;

    await post('/events/batch', { events: queue });
    await AsyncStorage.removeItem(EVENT_QUEUE_KEY);
    return queue.length;
  } catch {
    return 0;
  }
};
