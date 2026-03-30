/**
 * Shared recipe state provider.
 *
 * Page-based architecture:
 *
 *   All fetched recipes accumulate in `recipes[]`. The UI shows one page of
 *   PAGE_SIZE (5) at a time, controlled by `currentPage` (0-indexed).
 *
 *   After page 1 loads, a background prefetch eagerly pulls the next batch
 *   from the backend and appends it to `recipes[]`, so navigating forward
 *   is usually instant.
 *
 *   shownIdsRef  — Set of every recipe ID ever fetched. No-repeat guarantee.
 *
 * Substitution pre-fetching:
 *   prefetchSubstitutions(recipeId, recipeIngredients, userIngredients) is
 *   called from discover.js when each card is rendered. Results cached so
 *   recipe detail reads from cache immediately.
 */

import { createContext, useContext, useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useAuth } from './AuthContext';
import { useSession } from './SessionContext';
import { getRecommendations, getNextBatch, rerankPool } from '../services/pipelineService';
import { getSubstitutions } from '../services/recipeService';
import { trackEvent } from '../services/eventService';
import { RECIPE_BATCH_SIZE } from '../constants/config';

const RecipeContext = createContext(null);

const PAGE_SIZE = RECIPE_BATCH_SIZE; // 5
const PREFETCH_RETRY_DELAY_MS = 1500;
const PREFETCH_MAX_RETRIES = 20;
// Number of pages to keep buffered ahead of the user's current page
const PAGES_AHEAD = 3;

export function RecipeProvider({ children }) {
  const { user } = useAuth();
  const { session, updateSession, batchAddShownRecipeIds } = useSession();

  // All fetched recipes across every page (accumulated, never cleared mid-session)
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [poolInfo, setPoolInfo] = useState({ poolSize: 0, shownCount: 0 });

  // Current page index (0-based)
  const [currentPage, setCurrentPage] = useState(0);

  // True while a background prefetch to extend recipes[] is in flight
  const [isBuffering, setIsBuffering] = useState(false);
  // True when a "next page" tap is waiting for the prefetch to finish
  const [nextPagePending, setNextPagePending] = useState(false);

  // Substitutions cache: recipeId → { substitutions: [...], loading, done }
  const [substitutionsCache, setSubstitutionsCache] = useState({});

  // Synchronous refs
  const pipelineRunning = useRef(false);
  const prefetchingRef = useRef(false);
  const shownIdsRef = useRef(new Set());
  const recipesRef = useRef([]);   // mirrors recipes state for async closures
  const currentPageRef = useRef(0);  // mirrors currentPage for async closures

  // ── Internal: continuously prefetch batches until PAGES_AHEAD pages are buffered ─
  const _prefetchNextBatch = useCallback(async (poolId) => {
    if (prefetchingRef.current || !poolId) return;
    prefetchingRef.current = true;
    setIsBuffering(true);

    // Keep fetching batches until we have PAGES_AHEAD full pages beyond the current
    let consecutiveEmpties = 0;

    while (consecutiveEmpties <= PREFETCH_MAX_RETRIES) {
      // Check: do we already have enough pages buffered?
      const bufferedPages = Math.floor(recipesRef.current.length / PAGE_SIZE);
      const currentPg = currentPageRef.current;
      if (bufferedPages >= currentPg + 1 + PAGES_AHEAD) {
        // We have enough — stop prefetching
        break;
      }

      try {
        const result = await getNextBatch(poolId);
        const incoming = (result.recipes || []).filter(
          (r) => !shownIdsRef.current.has(r.id)
        );

        if (incoming.length > 0) {
          incoming.forEach((r) => shownIdsRef.current.add(r.id));
          setRecipes((prev) => {
            const updated = [...prev, ...incoming];
            recipesRef.current = updated;
            return updated;
          });
          // Never decrease poolSize — the initial response sets an optimistic
          // count that includes background-fetched recipes still in flight.
          setPoolInfo((prev) => ({
            poolSize: Math.max(prev.poolSize, result.poolSize),
            shownCount: result.shownCount,
          }));
          batchAddShownRecipeIds(incoming.map((r) => r.id));
          consecutiveEmpties = 0; // reset on success
          // Small delay between successful fetches to avoid hammering backend
          await new Promise((resolve) => setTimeout(resolve, 500));
        } else {
          // 0 new recipes — backend pool may still be populating.
          // Update poolSize (never decrease) so hasNextPage stays accurate.
          if (result.poolSize) {
            setPoolInfo((prev) => ({
              poolSize: Math.max(prev.poolSize, result.poolSize),
              shownCount: prev.shownCount,
            }));
          }
          consecutiveEmpties++;
          if (consecutiveEmpties <= PREFETCH_MAX_RETRIES) {
            // Use longer delays as we wait — background fetch may still be scraping
            const delay = Math.min(PREFETCH_RETRY_DELAY_MS * (1 + Math.floor(consecutiveEmpties / 3)), 5000);
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
      } catch (err) {
        console.warn('[RecipeContext] _prefetchNextBatch error:', err.message);
        consecutiveEmpties++;
        if (consecutiveEmpties <= PREFETCH_MAX_RETRIES) {
          await new Promise((resolve) => setTimeout(resolve, PREFETCH_RETRY_DELAY_MS));
        }
      }
    }

    prefetchingRef.current = false;
    setIsBuffering(false);
  }, [batchAddShownRecipeIds]);

  // ── startPipeline ─────────────────────────────────────────────────────────
  const startPipeline = useCallback(async (sessionContext) => {
    if (pipelineRunning.current) {
      console.warn('[RecipeContext] startPipeline already running — ignoring duplicate call');
      return;
    }
    pipelineRunning.current = true;
    if (!user?.id) {
      setError('Please log in to get recipe recommendations.');
      pipelineRunning.current = false;
      return;
    }

    // Full reset for new session
    setLoading(true);
    setError(null);
    setRecipes([]);
    setCurrentPage(0);
    setIsBuffering(false);
    setNextPagePending(false);
    setPoolInfo({ poolSize: 0, shownCount: 0 });
    setSubstitutionsCache({});
    prefetchingRef.current = false;
    shownIdsRef.current = new Set();
    recipesRef.current = [];
    currentPageRef.current = 0;

    try {
      const result = await getRecommendations(user.id, sessionContext);
      const firstPage = result.recipes || [];

      firstPage.forEach((r) => shownIdsRef.current.add(r.id));
      recipesRef.current = firstPage;

      setRecipes(firstPage);
      setCurrentPage(0);
      updateSession({ sessionPoolId: result.sessionPoolId });
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });
      batchAddShownRecipeIds(firstPage.map((r) => r.id));

      trackEvent({
        userId: user.id,
        sessionId: result.sessionPoolId,
        eventType: 'session_started',
        metadata: { mealType: sessionContext.mealType },
      }).catch(() => {});

      // Immediately pre-fetch page 2 data into recipes[]
      _prefetchNextBatch(result.sessionPoolId);
    } catch (err) {
      console.error('[RecipeContext] Pipeline error:', err.message, err);
      setError(err.message || 'Failed to load recipes. Please try again.');
    } finally {
      pipelineRunning.current = false;
      setLoading(false);
    }
  }, [user?.id, updateSession, batchAddShownRecipeIds, _prefetchNextBatch]);

  // ── Derived: current page recipes ─────────────────────────────────────────
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(recipes.length / PAGE_SIZE)),
    [recipes.length]
  );
  const currentPageRecipes = useMemo(
    () => recipes.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [recipes, currentPage]
  );
  const hasNextPage = useMemo(() => {
    const nextEnd = (currentPage + 1) * PAGE_SIZE + PAGE_SIZE;
    if (nextEnd <= recipes.length) return true; // full page of 5 ready
    // Data still coming — show as available so user sees loading state
    return poolInfo.poolSize > recipes.length || isBuffering || nextPagePending;
  }, [currentPage, recipes.length, poolInfo.poolSize, isBuffering, nextPagePending]);
  const hasPrevPage = currentPage > 0;

  // Keep currentPageRef in sync for the async prefetcher
  currentPageRef.current = currentPage;

  // ── Auto-advance page when pending and new recipes arrive ─────────────────
  const prevRecipesLenRef = useRef(0);
  useMemo(() => {
    prevRecipesLenRef.current = recipes.length;
  }, [recipes.length]);

  // ── nextPage ──────────────────────────────────────────────────────────────
  const nextPage = useCallback(async () => {
    if (!session.sessionPoolId) return;

    const nextStart = (currentPage + 1) * PAGE_SIZE;
    const nextEnd = nextStart + PAGE_SIZE;

    // Pool is exhausted when nothing is buffering and poolSize is fully loaded
    const poolExhausted = !isBuffering && !prefetchingRef.current &&
      poolInfo.poolSize > 0 && poolInfo.poolSize <= recipesRef.current.length;

    if (nextEnd <= recipesRef.current.length) {
      // Full page of PAGE_SIZE recipes available — advance immediately.
      const newPage = currentPage + 1;
      setCurrentPage(newPage);
      currentPageRef.current = newPage;

      // Keep prefetching to buffer ahead
      if (!prefetchingRef.current) {
        _prefetchNextBatch(session.sessionPoolId);
      }
    } else if (nextStart < recipesRef.current.length && poolExhausted) {
      // Partial last page — pool is done, show whatever we have
      const newPage = currentPage + 1;
      setCurrentPage(newPage);
      currentPageRef.current = newPage;
    } else if (prefetchingRef.current || isBuffering) {
      // Not enough data yet but prefetch in flight — show loading state
      setNextPagePending(true);
      // Ensure prefetch is running
      if (!prefetchingRef.current) {
        _prefetchNextBatch(session.sessionPoolId);
      }
    } else {
      // Not enough data, no prefetch — kick off a fetch now
      setNextPagePending(true);
      _prefetchNextBatch(session.sessionPoolId);
    }
  }, [session.sessionPoolId, currentPage, isBuffering, poolInfo.poolSize, _prefetchNextBatch]);

  // ── prevPage ──────────────────────────────────────────────────────────────
  const prevPage = useCallback(() => {
    setCurrentPage((p) => Math.max(0, p - 1));
  }, []);

  // ── Effect: auto-advance when pending and new data arrives ─────────────
  // We watch recipes.length; when it grows and nextPagePending is true, advance.
  const pendingRef = useRef(false);
  pendingRef.current = nextPagePending;

  // Using a ref + setState callback to avoid stale closure issues
  const handleRecipesGrew = useCallback(() => {
    if (!pendingRef.current) return;
    setCurrentPage((p) => {
      const nextStart = (p + 1) * PAGE_SIZE;
      const nextEnd = nextStart + PAGE_SIZE;
      const poolExhausted = !prefetchingRef.current &&
        poolInfo.poolSize > 0 && poolInfo.poolSize <= recipesRef.current.length;

      if (nextEnd <= recipesRef.current.length) {
        // Full PAGE_SIZE recipes available for next page — advance now.
        setNextPagePending(false);
        const newPage = p + 1;
        currentPageRef.current = newPage;
        // Re-trigger prefetch to keep buffer full
        if (session.sessionPoolId && !prefetchingRef.current) {
          _prefetchNextBatch(session.sessionPoolId);
        }
        return newPage;
      } else if (nextStart < recipesRef.current.length && poolExhausted) {
        // Partial last page — pool done, show what we have
        setNextPagePending(false);
        const newPage = p + 1;
        currentPageRef.current = newPage;
        return newPage;
      }
      // Not enough yet — stay on current page, keep waiting
      return p;
    });
  }, [session.sessionPoolId, _prefetchNextBatch, poolInfo.poolSize]);

  // Track recipes growth
  const lastRecipesLen = useRef(0);
  useMemo(() => {
    if (recipes.length > lastRecipesLen.current) {
      lastRecipesLen.current = recipes.length;
      // Schedule advance check after render
      setTimeout(handleRecipesGrew, 0);
    }
  }, [recipes.length, handleRecipesGrew]);

  // ── When buffering stops, check if we can advance with a partial last page ─
  // This handles the case where the pool is exhausted (PREFETCH_MAX_RETRIES hit)
  // but there are still some recipes available that don't fill a full page.
  useEffect(() => {
    if (!nextPagePending || isBuffering || prefetchingRef.current) return;
    const p = currentPageRef.current;
    const nextStart = (p + 1) * PAGE_SIZE;
    const poolExhausted = poolInfo.poolSize > 0 && poolInfo.poolSize <= recipesRef.current.length;
    if (nextStart < recipesRef.current.length && poolExhausted) {
      setCurrentPage(p + 1);
      currentPageRef.current = p + 1;
      setNextPagePending(false);
    }
  }, [isBuffering, nextPagePending, poolInfo.poolSize]);

  // ── prefetchSubstitutions ─────────────────────────────────────────────────
  const prefetchSubstitutions = useCallback(async (recipeId, recipeIngredients, userIngredients) => {
    if (!recipeId || !recipeIngredients || recipeIngredients.length === 0) return;

    setSubstitutionsCache((prev) => {
      if (prev[recipeId]) return prev;
      return { ...prev, [recipeId]: { loading: true, done: false, substitutions: null } };
    });

    try {
      const res = await getSubstitutions(recipeId, recipeIngredients, userIngredients || []);
      if (res?.substitutions && Array.isArray(res.substitutions)) {
        setSubstitutionsCache((prev) => ({
          ...prev,
          [recipeId]: { loading: false, done: true, substitutions: res.substitutions },
        }));
      } else {
        setSubstitutionsCache((prev) => ({
          ...prev,
          [recipeId]: { loading: false, done: true, substitutions: [] },
        }));
      }
    } catch {
      setSubstitutionsCache((prev) => ({
        ...prev,
        [recipeId]: { loading: false, done: true, substitutions: [] },
      }));
    }
  }, []);

  const rerank = useCallback(async (likedRecipeId, action) => {
    if (!user?.id || !session.sessionPoolId) return;
    try {
      await rerankPool(user.id, session.sessionPoolId, likedRecipeId, action);
    } catch {
      // Non-blocking
    }
  }, [user?.id, session.sessionPoolId]);

  const resetRecipes = useCallback(() => {
    setRecipes([]);
    setCurrentPage(0);
    setIsBuffering(false);
    setNextPagePending(false);
    setError(null);
    setPoolInfo({ poolSize: 0, shownCount: 0 });
    setSubstitutionsCache({});
    shownIdsRef.current = new Set();
    prefetchingRef.current = false;
    pipelineRunning.current = false;
    recipesRef.current = [];
    currentPageRef.current = 0;
    lastRecipesLen.current = 0;
  }, []);

  const value = useMemo(() => ({
    recipes,
    currentPage,
    currentPageRecipes,
    totalPages,
    hasNextPage,
    hasPrevPage,
    loading,
    error,
    poolInfo,
    isBuffering,
    nextPagePending,
    substitutionsCache,
    startPipeline,
    nextPage,
    prevPage,
    prefetchSubstitutions,
    rerank,
    resetRecipes,
  }), [
    recipes, currentPage, currentPageRecipes, totalPages,
    hasNextPage, hasPrevPage,
    loading, error, poolInfo,
    isBuffering, nextPagePending,
    substitutionsCache,
    startPipeline, nextPage, prevPage, prefetchSubstitutions, rerank, resetRecipes,
  ]);

  return (
    <RecipeContext.Provider value={value}>
      {children}
    </RecipeContext.Provider>
  );
}

export const useRecipeContext = () => {
  const context = useContext(RecipeContext);
  if (!context) {
    throw new Error('useRecipeContext must be used within a RecipeProvider');
  }
  return context;
};
