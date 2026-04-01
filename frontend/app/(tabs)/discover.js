/**
 * Recipe discovery screen — page-based.
 *
 * Shows exactly 5 recipes per page with Prev / Next navigation.
 * Pages are pre-fetched in the background so forward navigation is instant.
 *
 * Substitutions are pre-fetched as each card is rendered so recipe detail
 * reads from cache with zero LLM wait.
 *
 * UX notes:
 *   - Clicking "Next" never replaces the visible page with a full-screen
 *     loader. The current page stays visible while the next batch loads,
 *     with a phase progress banner shown at the top.
 *   - The list auto-scrolls to the top whenever the page advances.
 *   - Phase labels ("Brainstorming…", "Searching…", "Ranking…") give the
 *     user a sense of what the system is doing without exposing internals.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, Pressable, ActivityIndicator, FlatList, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useSession } from '../../src/context/SessionContext';
import { useRecipeContext } from '../../src/context/RecipeContext';
import { useSavedRecipesContext } from '../../src/context/SavedRecipesContext';
import RecipeCard from '../../src/components/common/RecipeCard';
import { RECIPE_BATCH_SIZE } from '../../src/constants/config';

const FATIGUE_THRESHOLD = 7;

/**
 * Phase labels shown in the progress banner while the next page is loading.
 * They cycle every 1.5 s to convey meaningful progression rather than a
 * generic spinner — mirrors the actual backend pipeline stages.
 */
const DISCOVERY_PHASES = [
  'Brainstorming ideas for your next page…',
  'Searching for matching recipes…',
  'Ranking by what you have on hand…',
];

export default function DiscoverScreen() {
  const router = useRouter();
  const { session, resetSession } = useSession();
  const {
    currentPage,
    currentPageRecipes,
    totalPages,
    hasNextPage,
    hasPrevPage,
    recipes,
    loading,
    error,
    llmWarning,
    poolInfo,
    isBuffering,
    nextPagePending,
    nextPage,
    prevPage,
    rerank,
    resetRecipes,
  } = useRecipeContext();
  const { save, remove, isSaved, savedRecipes } = useSavedRecipesContext();

  const [refreshCount, setRefreshCount] = useState(0);
  const [showFatiguePrompt, setShowFatiguePrompt] = useState(false);

  // Ref for programmatic scroll-to-top on page advance
  const flatListRef = useRef(null);

  // Cycling phase index — only advances while nextPagePending is true
  const [phaseIndex, setPhaseIndex] = useState(0);

  useEffect(() => {
    if (!nextPagePending) {
      setPhaseIndex(0);
      return;
    }
    const intervalId = setInterval(() => {
      setPhaseIndex((prev) => (prev + 1) % DISCOVERY_PHASES.length);
    }, 1500);
    return () => clearInterval(intervalId);
  }, [nextPagePending]);

  // Scroll to top whenever the visible page changes (covers both instant
  // and delayed advances).
  useEffect(() => {
    if (currentPage > 0) {
      flatListRef.current?.scrollToOffset({ offset: 0, animated: true });
    }
  }, [currentPage]);

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleStartSession = useCallback(() => {
    resetRecipes();
    resetSession();
    router.push('/session/setup');
  }, [resetRecipes, resetSession, router]);

  const handleNextPage = useCallback(() => {
    if (!session.sessionPoolId) return;

    setRefreshCount((c) => {
      const next = c + 1;
      if (next >= FATIGUE_THRESHOLD) setShowFatiguePrompt(true);
      return next;
    });

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    nextPage();
  }, [session.sessionPoolId, nextPage]);

  const handlePrevPage = useCallback(() => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    prevPage();
  }, [prevPage]);

  const handleSave = useCallback(async (recipe) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (isSaved(recipe.id)) {
      const savedEntry = savedRecipes.find((entry) => entry.recipeId === recipe.id);
      if (savedEntry) remove(savedEntry.id);
    } else {
      await save(recipe.id, session.sessionPoolId);
      rerank(recipe.id, 'saved').catch(() => {});
    }
  }, [isSaved, savedRecipes, save, remove, session.sessionPoolId, rerank]);

  const handlePress = useCallback((recipe) => {
    router.push('/recipe/' + recipe.id);
  }, [router]);

  // ── Derived state ────────────────────────────────────────────────────────

  const hasActiveSession = session.sessionPoolId != null || recipes.length > 0 || loading;

  // Only show the full-page loader on the very first load when no recipes
  // exist yet. Once the user has seen at least one page, keep showing it
  // while the next page loads — a phase banner handles that state instead.
  const isInitialLoading = (loading && recipes.length === 0) ||
    (currentPageRecipes.length < RECIPE_BATCH_SIZE &&
      recipes.length === 0 &&
      (isBuffering || poolInfo.poolSize > 0));

  const listData = useMemo(() => {
    if (isInitialLoading) return [];
    return currentPageRecipes;
  }, [isInitialLoading, currentPageRecipes]);

  // ── Render ───────────────────────────────────────────────────────────────

  const renderItem = useCallback(({ item }) => {
    return (
      <RecipeCard
        recipe={item}
        isSaved={isSaved(item.id)}
        onPress={() => handlePress(item)}
        onSave={() => handleSave(item)}
      />
    );
  }, [isSaved, handlePress, handleSave]);

  // ── Phase progress banner ────────────────────────────────────────────────

  /**
   * Shown at the top of the list while the next page is buffering.
   * Keeps the current page fully visible so the user has something to look at.
   */
  const NextPageBanner = useMemo(() => {
    if (!nextPagePending) return null;
    return (
      <View className="mb-4 px-4 py-3 bg-green-50 border border-green-100 rounded-2xl flex-row items-center gap-3">
        <ActivityIndicator size="small" color="#214130" />
        <View className="flex-1">
          <Text className="text-xs font-semibold text-primary">Loading your next page</Text>
          <Text className="text-xs text-green-600 mt-0.5">{DISCOVERY_PHASES[phaseIndex]}</Text>
        </View>
      </View>
    );
  }, [nextPagePending, phaseIndex]);

  // ── Pagination controls ─────────────────────────────────────────────────

  const PaginationBar = useMemo(() => {
    if (!session.sessionPoolId || recipes.length === 0) return null;

    const isLoadingNext = nextPagePending || (isBuffering && !hasNextPage);

    return (
      <View className="mt-4 mb-2">
        {showFatiguePrompt ? (
          <View className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-2xl">
            <Text className="text-sm font-semibold text-amber-800 mb-1">Having trouble deciding?</Text>
            <Text className="text-sm text-amber-700 mb-3">Start a new session to refine your search.</Text>
            <Pressable
              onPress={() => { setShowFatiguePrompt(false); handleStartSession(); }}
              className="bg-amber-600 px-4 py-2 rounded-lg self-start"
            >
              <Text className="text-white text-sm font-semibold">Start New Session</Text>
            </Pressable>
          </View>
        ) : null}

        <View className="flex-row items-center justify-between">
          {/* Prev button */}
          <Pressable
            onPress={handlePrevPage}
            disabled={!hasPrevPage}
            className={
              'flex-row items-center gap-1 px-4 py-3 rounded-xl ' +
              (hasPrevPage ? 'bg-surface border border-border active:opacity-80' : 'opacity-30')
            }
            accessibilityRole="button"
            accessibilityLabel="Previous page"
          >
            <Ionicons name="chevron-back" size={18} color={hasPrevPage ? '#214130' : '#94A3B8'} />
            <Text className={'text-sm font-semibold ' + (hasPrevPage ? 'text-primary' : 'text-text-muted')}>
              Prev
            </Text>
          </Pressable>

          {/* Page indicator */}
          <View className="items-center">
            <Text className="text-sm font-semibold text-text-primary">
              Page {currentPage + 1}
            </Text>
          </View>

          {/* Next button */}
          <Pressable
            onPress={handleNextPage}
            disabled={!hasNextPage || isLoadingNext}
            className={
              'flex-row items-center gap-1 px-4 py-3 rounded-xl ' +
              (hasNextPage && !isLoadingNext
                ? 'bg-primary active:opacity-80'
                : isLoadingNext
                  ? 'bg-green-100 border border-green-200'
                  : 'opacity-30 bg-surface border border-border')
            }
            accessibilityRole="button"
            accessibilityLabel={isLoadingNext ? 'Loading next page' : 'Next page'}
          >
            {isLoadingNext ? (
              <>
                <ActivityIndicator size="small" color="#214130" />
                <Text className="text-sm font-semibold text-primary ml-1">Loading…</Text>
              </>
            ) : (
              <>
                <Text className={'text-sm font-semibold ' + (hasNextPage ? 'text-white' : 'text-text-muted')}>
                  Next
                </Text>
                <Ionicons name="chevron-forward" size={18} color={hasNextPage ? '#FFFFFF' : '#94A3B8'} />
              </>
            )}
          </Pressable>
        </View>
      </View>
    );
  }, [
    session.sessionPoolId, recipes.length,
    currentPage, totalPages, hasNextPage, hasPrevPage,
    isBuffering, nextPagePending, poolInfo,
    showFatiguePrompt, handleStartSession,
    handleNextPage, handlePrevPage,
  ]);

  // Full green background when no active session (home/empty state).
  const isEmptyState = !hasActiveSession && !loading;

  return (
    <SafeAreaView
      className="flex-1"
      style={{ backgroundColor: isEmptyState ? '#214130' : '#FAFAFA' }}
    >
      {/* Header — hidden during the empty state so the green fills edge-to-edge */}
      {!isEmptyState && (
        <View className="px-6 pt-4 pb-2 flex-row items-center justify-between">
          <Text className="text-2xl font-bold text-text-primary">Discover</Text>
          <View className="flex-row items-center gap-3">
            {hasActiveSession ? (
              <Pressable
                onPress={handleStartSession}
                className="flex-row items-center gap-1 px-3 py-1.5 rounded-full border border-border"
                accessibilityLabel="Start new session"
              >
                <Ionicons name="refresh-outline" size={14} color="#64748B" />
                <Text className="text-xs font-medium text-text-secondary">New</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      )}

      {isEmptyState ? (
        <EmptyState onStart={handleStartSession} />
      ) : isInitialLoading && hasActiveSession ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color="#214130" />
          <Text className="text-sm text-text-secondary mt-3 font-medium">
            Finding great recipes for you…
          </Text>
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          data={listData}
          extraData={savedRecipes}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          ListHeaderComponent={
            <>
              {/* Phase banner: visible while next page is loading */}
              {NextPageBanner}
              {llmWarning ? (
                <View className="mb-2 py-3 bg-amber-50 border border-amber-200 rounded-xl flex-row items-center gap-2 px-4">
                  <Ionicons name="information-circle-outline" size={16} color="#D97706" />
                  <Text className="text-sm text-amber-800 flex-1">{llmWarning}</Text>
                </View>
              ) : null}
              {error ? (
                <View className="mb-2 py-3 bg-red-50 border border-red-200 rounded-xl flex-row items-center gap-2 px-4">
                  <Ionicons name="warning-outline" size={16} color="#DC2626" />
                  <Text className="text-sm text-red-600 flex-1">{error}</Text>
                </View>
              ) : null}
              {session.sessionPoolId ? (
                <View className="flex-row items-center gap-2 mb-4 py-2 px-3 bg-green-50 rounded-xl">
                  <Ionicons name="restaurant-outline" size={14} color="#214130" />
                  <Text className="text-xs font-medium text-primary capitalize">
                    {session.mealType} · {session.servingCount} serving{session.servingCount !== 1 ? 's' : ''}
                    {session.occasion ? ' · ' + session.occasion : ''}
                  </Text>
                </View>
              ) : null}
            </>
          }
          ListFooterComponent={PaginationBar}
          contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 24 }}
          showsVerticalScrollIndicator={false}
          removeClippedSubviews
          initialNumToRender={RECIPE_BATCH_SIZE}
          maxToRenderPerBatch={RECIPE_BATCH_SIZE}
          windowSize={3}
        />
      )}
    </SafeAreaView>
  );
}

/**
 * Full-screen dark-green home state shown when no active session exists yet.
 * Bold Mohave display font headline, white CTA — no icon, pure typography.
 *
 * Layout: spacer fills the top ~45% so content naturally sits in the lower
 * half; this guarantees the button is always visible regardless of device height.
 *
 * @param {object} props
 * @param {function} props.onStart - Called when the user taps "Find Me Now".
 */
function EmptyState({ onStart }) {
  return (
    <ScrollView
      contentContainerStyle={{
        flexGrow: 1,
        justifyContent: 'flex-end',
        paddingHorizontal: 32,
        paddingBottom: 52,
      }}
      scrollEnabled={false}
      keyboardShouldPersistTaps="handled"
    >
      <Text
        style={{
          fontFamily: 'Mohave_700Bold',
          fontSize: 50,
          color: '#FFFFFF',
          lineHeight: 56,
          letterSpacing: -1,
          marginBottom: 36,
        }}
        accessibilityRole="header"
      >
        The internet has millions of recipes.{'\n'}You only need one.{'\n'}We'll find it.
      </Text>

      <Pressable
        onPress={onStart}
        style={{
          backgroundColor: '#FFFFFF',
          paddingVertical: 18,
          borderRadius: 16,
          alignItems: 'center',
        }}
        accessibilityRole="button"
        accessibilityLabel="Find me a recipe now"
      >
        <Text
          style={{
            fontFamily: 'Mohave_700Bold',
            color: '#214130',
            fontSize: 18,
            letterSpacing: 0.3,
          }}
        >
          Find Me Now
        </Text>
      </Pressable>
    </ScrollView>
  );
}
