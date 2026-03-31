/**
 * Recipe discovery state provider.
 *
 * Architecture — page-based pagination with eager prefetch:
 *
 *   All fetched recipes accumulate in ``recipes[]``. The UI shows one page of
 *   PAGE_SIZE (5) at a time, controlled by ``currentPage`` (0-indexed).
 *
 *   After page 1 loads, the prefetcher eagerly pulls the next 8 pages from the
 *   backend pool in the background so forward navigation is almost always
 *   instant. The prefetcher uses exponential back-off when the pool is still
 *   being populated (background web scraping still in progress).
 *
 *   ``shownIdsRef`` — Set of every recipe ID ever delivered to the UI.
 *   Guarantees no recipe is shown twice within a session.
 *
 * Ref mirrors:
 *   ``recipesRef`` and ``currentPageRef`` mirror their corresponding state
 *   values for use inside async callbacks (closures capture the ref, not the
 *   stale state). This is the canonical pattern for async state access in
 *   React — see coding_standards.md §6.1.
 *
 * Substitution pre-fetching:
 *   ``prefetchSubstitutions()`` is called as each card enters the viewport.
 *   Results are cached in ``substitutionsCache`` so the Recipe Detail screen
 *   can display substitution data with zero LLM wait.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useAuth } from './AuthContext';
import { useSession } from './SessionContext';
import { getRecommendations, getNextBatch, rerankPool } from '../services/pipelineService';
import { getSubstitutions } from '../services/recipeService';
import { trackEvent } from '../services/eventService';
import { RECIPE_BATCH_SIZE } from '../constants/config';

const RecipeContext = createContext(null);

const PAGE_SIZE = RECIPE_BATCH_SIZE; // 5
const PREFETCH_RETRY_DELAY_MS = 800;
const PREFETCH_MAX_RETRIES = 30;
// Buffer all available recipes aggressively (backend generates ~40 = 8 pages)
const PAGES_AHEAD = 8;

/**
 * Provides recipe discovery state and navigation actions to the component tree.
 *
 * @param {{ children: React.ReactNode }} props
 */
export function RecipeProvider({ children }) {
  const { user } = useAuth();
  const { session, updateSession, batchAddShownRecipeIds } = useSession();

  // All fetched recipes across every page (accumulated, never cleared mid-session)
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [llmWarning, setLlmWarning] = useState(null);
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

  // ── Prefetch loop ────────────────────────────────────────────────────────
  /**
   * Continuously fetch recipe batches from the backend pool until
   * PAGES_AHEAD full pages are buffered beyond the current page.
   *
   * Uses exponential back-off (up to 5 s) when the pool is still being
   * populated by the background web-scraping task. Stops automatically once
   * the buffer target is met or PREFETCH_MAX_RETRIES consecutive empty
   * responses are received.
   *
   * @param {string} poolId - The session pool ID to fetch from.
   */
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

        console.log(
          `[prefetch] getNextBatch returned ${(result.recipes || []).length} recipes, ` +
          `${incoming.length} new (after dedup), recipesLen=${recipesRef.current.length}, ` +
          `poolSize=${result.poolSize}, consecutiveEmpties=${consecutiveEmpties}`
        );

        if (incoming.length > 0) {
          incoming.forEach((r) => shownIdsRef.current.add(r.id));
          setRecipes((prev) => {
            const updated = [...prev, ...incoming];
            recipesRef.current = updated;
            console.log(`[prefetch] recipes buffer grew: ${prev.length} → ${updated.length}`);
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
          // Minimal delay between successful fetches — get all recipes fast
          await new Promise((resolve) => setTimeout(resolve, 100));
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
            const delay = Math.min(PREFETCH_RETRY_DELAY_MS * (1 + Math.floor(consecutiveEmpties / 3)), 2500);
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

    console.log(
      `[prefetch] loop ended — consecutiveEmpties=${consecutiveEmpties}, ` +
      `recipesLen=${recipesRef.current.length}, bufferedPages=${Math.floor(recipesRef.current.length / PAGE_SIZE)}`
    );
    prefetchingRef.current = false;
    setIsBuffering(false);
  }, [batchAddShownRecipeIds]);

  // ── Pipeline start ────────────────────────────────────────────────────────
  /**
   * Start a new recipe recommendation pipeline for the given session context.
   *
   * Resets all recipe and pagination state, calls the backend pipeline, loads
   * the first page of results, and immediately begins background prefetching
   * of subsequent pages.
   *
   * Guards against duplicate calls — a second call while the pipeline is
   * running is silently ignored.
   *
   * @param {object} sessionContext - Session parameters (meal type, time, ingredients, etc.)
   */
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

      console.log(
        `[startPipeline] pipeline returned ${firstPage.length} recipes, ` +
        `poolSize=${result.poolSize}, shownCount=${result.shownCount}`
      );

      firstPage.forEach((r) => shownIdsRef.current.add(r.id));
      recipesRef.current = firstPage;

      setRecipes(firstPage);
      setCurrentPage(0);
      updateSession({ sessionPoolId: result.sessionPoolId });
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });
      setLlmWarning(result.llmWarning || null);
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

  // ── nextPage ──────────────────────────────────────────────────────────────
  const nextPage = useCallback(async () => {
    if (!session.sessionPoolId) return;

    const nextStart = (currentPage + 1) * PAGE_SIZE;
    const nextEnd = nextStart + PAGE_SIZE;

    // Pool is exhausted when nothing is buffering and poolSize is fully loaded
    const poolExhausted = !isBuffering && !prefetchingRef.current &&
      poolInfo.poolSize > 0 && poolInfo.poolSize <= recipesRef.current.length;

    console.log(
      `[nextPage] currentPage=${currentPage}, recipesLen=${recipesRef.current.length}, ` +
      `nextStart=${nextStart}, nextEnd=${nextEnd}, poolSize=${poolInfo.poolSize}, ` +
      `isBuffering=${isBuffering}, prefetching=${prefetchingRef.current}, poolExhausted=${poolExhausted}`
    );

    if (nextEnd <= recipesRef.current.length) {
      console.log('[nextPage] BRANCH: full page available — advancing');
      // Full page of PAGE_SIZE recipes available — advance immediately.
      const newPage = currentPage + 1;
      setCurrentPage(newPage);
      currentPageRef.current = newPage;

      // Keep prefetching to buffer ahead
      if (!prefetchingRef.current) {
        _prefetchNextBatch(session.sessionPoolId);
      }
    } else if (nextStart < recipesRef.current.length && poolExhausted) {
      console.log('[nextPage] BRANCH: partial last page (pool exhausted) — advancing');
      // Partial last page — pool is done, show whatever we have
      const newPage = currentPage + 1;
      setCurrentPage(newPage);
      currentPageRef.current = newPage;
    } else if (prefetchingRef.current || isBuffering) {
      console.log('[nextPage] BRANCH: not enough data, prefetch in flight — PENDING');
      // Not enough data yet but prefetch in flight — show loading state
      setNextPagePending(true);
      // Ensure prefetch is running
      if (!prefetchingRef.current) {
        _prefetchNextBatch(session.sessionPoolId);
      }
    } else {
      console.log('[nextPage] BRANCH: not enough data, no prefetch — PENDING + kick fetch');
      // Not enough data, no prefetch — kick off a fetch now
      setNextPagePending(true);
      _prefetchNextBatch(session.sessionPoolId);
    }
  }, [session.sessionPoolId, currentPage, isBuffering, poolInfo.poolSize, _prefetchNextBatch]);

  // ── prevPage ──────────────────────────────────────────────────────────────
  const prevPage = useCallback(() => {
    setCurrentPage((p) => Math.max(0, p - 1));
    // User is actively browsing — ensure background prefetch is running so
    // recipes keep accumulating for when they navigate forward again.
    if (session.sessionPoolId && !prefetchingRef.current) {
      _prefetchNextBatch(session.sessionPoolId);
    }
  }, [session.sessionPoolId, _prefetchNextBatch]);

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

  // Watch recipes.length growth and schedule a pending-page advance check.
  // useEffect (not useMemo) because this is a side effect — it calls
  // setTimeout and mutates lastRecipesLen.current — not a derived value.
  const lastRecipesLen = useRef(0);
  useEffect(() => {
    if (recipes.length > lastRecipesLen.current) {
      lastRecipesLen.current = recipes.length;
      // Schedule the advance check after the render that updated recipes[]
      // so recipesRef.current is fully up-to-date when handleRecipesGrew runs.
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
    } else if (poolExhausted) {
      // Pool is truly exhausted — nothing more to show, clear the pending state
      setNextPagePending(false);
    } else if (session.sessionPoolId) {
      // Pool may still be building (re-ideation in progress) — restart prefetch
      // after a short pause so we don't spin-hammer the backend immediately.
      const timer = setTimeout(() => {
        if (pendingRef.current && !prefetchingRef.current) {
          _prefetchNextBatch(session.sessionPoolId);
        }
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isBuffering, nextPagePending, poolInfo.poolSize, session.sessionPoolId, _prefetchNextBatch]);

  // ── Proactive prefetch: restart when buffer ahead drops below 20 recipes ────
  // Triggers independently of user navigation so background fetching starts
  // before the user reaches the end of what's buffered. Uses a threshold of
  // 4 pages (20 recipes) ahead of the current page.
  useEffect(() => {
    if (!session.sessionPoolId || prefetchingRef.current) return;
    const remaining = recipesRef.current.length - (currentPage + 1) * PAGE_SIZE;
    if (remaining < 4 * PAGE_SIZE && poolInfo.poolSize > recipesRef.current.length) {
      _prefetchNextBatch(session.sessionPoolId);
    }
  }, [currentPage, recipes.length, poolInfo.poolSize, session.sessionPoolId, _prefetchNextBatch]);

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
    setLlmWarning(null);
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
    llmWarning,
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
    loading, error, llmWarning, poolInfo,
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

/**
 * Hook to consume RecipeContext.
 *
 * @returns {object} Recipe state and navigation actions from the nearest RecipeProvider.
 * @throws {Error} If called outside a RecipeProvider.
 */
export const useRecipeContext = () => {
  const context = useContext(RecipeContext);
  if (!context) {
    throw new Error('useRecipeContext must be used inside a RecipeProvider');
  }
  return context;
};
