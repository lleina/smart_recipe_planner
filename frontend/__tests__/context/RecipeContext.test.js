/**
 * RecipeContext integration tests.
 *
 * Tests the REAL RecipeContext using @testing-library/react-native renderHook.
 * All external dependencies (API services, auth, session) are mocked so the
 * tests run offline with deterministic data and never hit a real server.
 *
 * What is actually tested here:
 *   - startPipeline() populates recipes and sets sessionPoolId
 *   - nextPage() advances page instantly when next page is buffered
 *   - nextPage() sets nextPagePending when data hasn't arrived yet,
 *     then auto-advances when the prefetch resolves
 *   - prevPage() decrements page and clamps at 0
 *   - hasNextPage / hasPrevPage derived values are correct
 *   - currentPageRecipes slices the right 5 recipes per page
 *   - No duplicate recipe IDs accumulate across prefetch batches
 *   - resetRecipes() clears all state
 *
 * Run: npm test -- --testPathPattern=RecipeContext
 */

import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import { RecipeProvider, useRecipeContext } from '../../src/context/RecipeContext';

// ── Mock all external dependencies ──────────────────────────────────────────

jest.mock('../../src/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'test-user-id' } }),
}));

jest.mock('../../src/context/SessionContext', () => {
  const updateSession = jest.fn();
  const batchAddShownRecipeIds = jest.fn();
  return {
    useSession: () => ({
      session: { sessionPoolId: 'mock-pool-id' },
      updateSession,
      batchAddShownRecipeIds,
    }),
  };
});

jest.mock('../../src/services/eventService', () => ({
  trackEvent: jest.fn(() => Promise.resolve()),
}));

jest.mock('../../src/services/recipeService', () => ({
  getSubstitutions: jest.fn(() => Promise.resolve({ substitutions: [] })),
}));

// pipelineService is the main mock we control per-test
jest.mock('../../src/services/pipelineService');
const { getRecommendations, getNextBatch } = require('../../src/services/pipelineService');

// ── Fixtures ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 5;

/**
 * Creates an array of minimal recipe objects with sequential IDs.
 * @param {number} count - How many recipes to create.
 * @param {number} [startId=1] - ID offset so multiple batches don't overlap.
 */
function makeRecipes(count, startId = 1) {
  return Array.from({ length: count }, (_, i) => ({
    id: `recipe-${startId + i}`,
    title: `Recipe ${startId + i}`,
    ingredients: ['ingredient'],
    instructions: ['step'],
    totalTime: 30,
    difficulty: 'easy',
    matchedIngredientCount: 1,
    totalIngredientCount: 1,
    ingredientMatchPct: 100,
  }));
}

/** Wrapper that provides RecipeProvider to all hooks under test. */
function wrapper({ children }) {
  return <RecipeProvider>{children}</RecipeProvider>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Starts the pipeline, drains all timers (so the prefetcher's backoff delays
 * resolve instantly), and waits for loading to finish.
 */
async function startAndWait(result) {
  await act(async () => {
    result.current.startPipeline({ mealType: 'dinner', servingCount: 2 });
  });
  await drainTimers();
  await waitFor(() => expect(result.current.loading).toBe(false));
}

// ── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  // Default: prefetch returns empty immediately — the prefetcher will
  // retry with setTimeout delays, which we skip via jest.runAllTimersAsync().
  getNextBatch.mockResolvedValue({ recipes: [], poolSize: 5, shownCount: 5 });
});

afterEach(() => {
  jest.useRealTimers();
});

/**
 * Drains all pending timers and microtasks so the prefetcher's retry loop
 * (which uses setTimeout for backoff delays) finishes in test time.
 */
async function drainTimers() {
  await act(async () => {
    await jest.runAllTimersAsync();
  });
}

// ── Initial state ─────────────────────────────────────────────────────────────

describe('initial state', () => {
  test('starts with no recipes, not loading, page 0', () => {
    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    expect(result.current.recipes).toHaveLength(0);
    expect(result.current.loading).toBe(false);
    expect(result.current.currentPage).toBe(0);
    expect(result.current.error).toBeNull();
  });

  test('hasPrevPage is false on page 0', () => {
    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    expect(result.current.hasPrevPage).toBe(false);
  });
});

// ── startPipeline ─────────────────────────────────────────────────────────────

describe('startPipeline', () => {
  test('sets loading=true while pipeline runs, then false', async () => {
    // Delay the response so we can observe loading=true mid-flight
    let resolveRecommend;
    getRecommendations.mockReturnValueOnce(
      new Promise((res) => { resolveRecommend = res; })
    );

    const { result } = renderHook(() => useRecipeContext(), { wrapper });

    act(() => {
      result.current.startPipeline({ mealType: 'dinner' });
    });

    // While promise is pending, loading should be true
    expect(result.current.loading).toBe(true);

    // Resolve the pipeline
    await act(async () => {
      resolveRecommend({
        sessionPoolId: 'pool-1',
        recipes: makeRecipes(PAGE_SIZE),
        poolSize: 40,
        shownCount: PAGE_SIZE,
      });
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  test('populates recipes with the first page from the pipeline', async () => {
    const firstPage = makeRecipes(PAGE_SIZE);
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: firstPage,
      poolSize: 40,
      shownCount: PAGE_SIZE,
    });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.recipes).toHaveLength(PAGE_SIZE);
    expect(result.current.recipes[0].id).toBe('recipe-1');
    expect(result.current.currentPage).toBe(0);
  });

  test('currentPageRecipes shows exactly the first 5', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE),
      poolSize: 40,
      shownCount: PAGE_SIZE,
    });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.currentPageRecipes).toHaveLength(PAGE_SIZE);
    expect(result.current.currentPageRecipes[0].id).toBe('recipe-1');
    expect(result.current.currentPageRecipes[4].id).toBe('recipe-5');
  });

  test('sets error and clears loading when pipeline throws', async () => {
    getRecommendations.mockRejectedValueOnce(new Error('LLM timeout'));

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.error).toMatch(/LLM timeout/);
    expect(result.current.recipes).toHaveLength(0);
  });

  test('ignores duplicate startPipeline calls while one is running', async () => {
    let resolveFirst;
    getRecommendations.mockReturnValueOnce(
      new Promise((res) => { resolveFirst = res; })
    );

    const { result } = renderHook(() => useRecipeContext(), { wrapper });

    act(() => { result.current.startPipeline({ mealType: 'dinner' }); });
    act(() => { result.current.startPipeline({ mealType: 'lunch' }); }); // duplicate

    await act(async () => {
      resolveFirst({
        sessionPoolId: 'pool-1',
        recipes: makeRecipes(PAGE_SIZE),
        poolSize: 40,
        shownCount: PAGE_SIZE,
      });
    });

    // getRecommendations should only have been called once
    expect(getRecommendations).toHaveBeenCalledTimes(1);
  });

  test('poolInfo is populated from the pipeline response', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE),
      poolSize: 40,
      shownCount: PAGE_SIZE,
    });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.poolInfo.poolSize).toBe(40);
    expect(result.current.poolInfo.shownCount).toBe(PAGE_SIZE);
  });
});

// ── nextPage / prevPage ───────────────────────────────────────────────────────

describe('nextPage — instant advance when data is buffered', () => {
  test('advances to page 1 immediately when 10 recipes are in the buffer', async () => {
    // First page from pipeline
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),        // recipes 1–5
      poolSize: 40,
      shownCount: PAGE_SIZE,
    });
    // Prefetcher loads recipes 6–10 on first call
    getNextBatch
      .mockResolvedValueOnce({
        recipes: makeRecipes(PAGE_SIZE, 6),       // recipes 6–10
        poolSize: 40,
        shownCount: PAGE_SIZE * 2,
      })
      .mockResolvedValue({ recipes: [], poolSize: 40, shownCount: PAGE_SIZE * 2 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    // Drain timers so prefetch completes and page 2 is buffered
    await drainTimers();
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 2));

    // nextPage should advance immediately — no loading, no pending
    await act(async () => {
      result.current.nextPage();
    });

    expect(result.current.currentPage).toBe(1);
    expect(result.current.nextPagePending).toBe(false);
    expect(result.current.currentPageRecipes[0].id).toBe('recipe-6');
    expect(result.current.currentPageRecipes[4].id).toBe('recipe-10');
  });

  test('page 2 shows correct recipes after two nextPage calls', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),
      poolSize: 40,
      shownCount: 5,
    });
    // Prefetcher returns pages 2 and 3
    getNextBatch
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 6), poolSize: 40, shownCount: 10 })
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 11), poolSize: 40, shownCount: 15 })
      .mockResolvedValue({ recipes: [], poolSize: 40, shownCount: 15 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    await drainTimers();
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 3));

    await act(async () => { result.current.nextPage(); });
    await act(async () => { result.current.nextPage(); });

    expect(result.current.currentPage).toBe(2);
    expect(result.current.currentPageRecipes[0].id).toBe('recipe-11');
  });

  test('hasPrevPage becomes true after nextPage, false again after prevPage', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),
      poolSize: 40,
      shownCount: 5,
    });
    getNextBatch
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 6), poolSize: 40, shownCount: 10 })
      .mockResolvedValue({ recipes: [], poolSize: 40, shownCount: 10 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 2));

    await drainTimers();
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 2));

    expect(result.current.hasPrevPage).toBe(false);

    await act(async () => { result.current.nextPage(); });
    expect(result.current.hasPrevPage).toBe(true);

    await act(async () => { result.current.prevPage(); });
    expect(result.current.hasPrevPage).toBe(false);
    expect(result.current.currentPage).toBe(0);
  });
});

describe('nextPage — pending state when data not yet buffered', () => {
  test('sets nextPagePending when next page not buffered yet', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),   // only 5 recipes
      poolSize: 40,                          // pool promises more
      shownCount: 5,
    });
    // Prefetch stalls — returns nothing initially
    getNextBatch.mockResolvedValue({ recipes: [], poolSize: 40, shownCount: 5 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    await act(async () => {
      result.current.nextPage();
    });

    // Can't advance yet — data not ready
    expect(result.current.currentPage).toBe(0);
    expect(result.current.nextPagePending).toBe(true);
  });

  test('auto-advances once prefetch delivers the next page', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),
      poolSize: 40,
      shownCount: 5,
    });

    // Call 1 (from startPipeline prefetch): empty — prefetcher stalls on setTimeout.
    // Call 2 (after timer fires): delivers page 2.
    // Subsequent: empty.
    getNextBatch
      .mockResolvedValueOnce({ recipes: [], poolSize: 40, shownCount: 5 })
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 6), poolSize: 40, shownCount: 10 })
      .mockResolvedValue({ recipes: [], poolSize: 40, shownCount: 10 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });

    // Start pipeline WITHOUT drainTimers so the prefetcher is stalled mid-retry.
    // (drainTimers would deliver recipes 6–10 before nextPage is called, which
    //  would make the test skip the pending state entirely.)
    await act(async () => {
      result.current.startPipeline({ mealType: 'dinner', servingCount: 2 });
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Only the first page should be loaded — prefetcher is stalled.
    expect(result.current.recipes).toHaveLength(PAGE_SIZE);

    // Tap next — prefetch is in flight (isBuffering=true), so pending fires.
    await act(async () => { result.current.nextPage(); });
    expect(result.current.nextPagePending).toBe(true);

    // Now drain timers — the stalled setTimeout fires, prefetcher retries,
    // getNextBatch returns page 2, recipes grows, handleRecipesGrew auto-advances.
    await drainTimers();

    await waitFor(() => expect(result.current.currentPage).toBe(1));
    expect(result.current.nextPagePending).toBe(false);
    expect(result.current.currentPageRecipes[0].id).toBe('recipe-6');
  });
});

describe('prevPage', () => {
  test('decrements currentPage', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE, 1),
      poolSize: 40,
      shownCount: 5,
    });
    getNextBatch
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 6), poolSize: 40, shownCount: 10 })
      .mockResolvedValue({ recipes: [], poolSize: 40, shownCount: 10 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);
    await drainTimers();
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 2));

    await act(async () => { result.current.nextPage(); });
    expect(result.current.currentPage).toBe(1);

    await act(async () => { result.current.prevPage(); });
    expect(result.current.currentPage).toBe(0);
  });

  test('clamps at 0 — cannot go below first page', async () => {
    const { result } = renderHook(() => useRecipeContext(), { wrapper });

    await act(async () => { result.current.prevPage(); });
    expect(result.current.currentPage).toBe(0);

    await act(async () => { result.current.prevPage(); });
    expect(result.current.currentPage).toBe(0);
  });
});

// ── Duplicate prevention ──────────────────────────────────────────────────────

describe('no duplicate recipes across prefetch batches', () => {
  test('recipes array never contains the same id twice', async () => {
    const page1 = makeRecipes(PAGE_SIZE, 1);
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: page1,
      poolSize: 15,
      shownCount: 5,
    });

    // Prefetcher returns pages 2 and 3
    getNextBatch
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 6), poolSize: 15, shownCount: 10 })
      .mockResolvedValueOnce({ recipes: makeRecipes(PAGE_SIZE, 11), poolSize: 15, shownCount: 15 })
      .mockResolvedValue({ recipes: [], poolSize: 15, shownCount: 15 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);
    await drainTimers();
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE * 3));

    const ids = result.current.recipes.map((r) => r.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  test('re-delivered ids from a second prefetch call are filtered out', async () => {
    const page1 = makeRecipes(PAGE_SIZE, 1);
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: page1,
      poolSize: 10,
      shownCount: 5,
    });

    // Backend mistakenly returns recipe-1 again in the next batch
    const duplicateIncluded = [
      { id: 'recipe-1', title: 'Recipe 1 (duplicate)', ingredients: [], instructions: [], totalTime: 30, difficulty: 'easy' },
      ...makeRecipes(PAGE_SIZE - 1, 6),
    ];
    getNextBatch
      .mockResolvedValueOnce({ recipes: duplicateIncluded, poolSize: 10, shownCount: 10 })
      .mockResolvedValue({ recipes: [], poolSize: 10, shownCount: 10 });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);
    await waitFor(() => expect(result.current.recipes.length).toBeGreaterThanOrEqual(PAGE_SIZE + 1));

    const ids = result.current.recipes.map((r) => r.id);
    const uniqueIds = new Set(ids);
    // recipe-1 must appear exactly once despite being in both batches
    expect(uniqueIds.size).toBe(ids.length);
    expect(ids.filter((id) => id === 'recipe-1')).toHaveLength(1);
  });
});

// ── resetRecipes ──────────────────────────────────────────────────────────────

describe('resetRecipes', () => {
  test('clears all state back to initial values', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE),
      poolSize: 40,
      shownCount: 5,
    });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.recipes.length).toBeGreaterThan(0);

    await act(async () => { result.current.resetRecipes(); });

    expect(result.current.recipes).toHaveLength(0);
    expect(result.current.currentPage).toBe(0);
    expect(result.current.error).toBeNull();
    expect(result.current.isBuffering).toBe(false);
    expect(result.current.nextPagePending).toBe(false);
    expect(result.current.poolInfo).toEqual({ poolSize: 0, shownCount: 0 });
  });
});

// ── hasNextPage derived value ─────────────────────────────────────────────────

describe('hasNextPage', () => {
  test('false when only one page and pool is exhausted', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE),
      poolSize: PAGE_SIZE,   // pool fully consumed by first page
      shownCount: PAGE_SIZE,
    });
    getNextBatch.mockResolvedValue({ recipes: [], poolSize: PAGE_SIZE, shownCount: PAGE_SIZE });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    // Drain timers so prefetch retry loop finishes and isBuffering clears
    await drainTimers();
    await waitFor(() => expect(result.current.isBuffering).toBe(false));

    expect(result.current.hasNextPage).toBe(false);
  });

  test('true when pool promises more recipes than currently buffered', async () => {
    getRecommendations.mockResolvedValueOnce({
      sessionPoolId: 'pool-1',
      recipes: makeRecipes(PAGE_SIZE),
      poolSize: 40,           // 40 total but only 5 loaded
      shownCount: PAGE_SIZE,
    });

    const { result } = renderHook(() => useRecipeContext(), { wrapper });
    await startAndWait(result);

    expect(result.current.hasNextPage).toBe(true);
  });
});
