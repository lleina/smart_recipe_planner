/**
 * Recipe discovery screen — page-based.
 *
 * Shows exactly 5 recipes per page with Prev / Next navigation.
 * Pages are pre-fetched in the background so forward navigation is instant.
 *
 * Substitutions are pre-fetched as each card is rendered so recipe detail
 * reads from cache with zero LLM wait.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
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

  // Determine whether to show REAL cards or a full-page loading indicator.
  // NEVER show skeleton cards — the user either sees 5 real cards or a loading page.
  const isPageLoading = useMemo(() => {
    // Initial load: no recipes at all yet
    if (loading && recipes.length === 0) return true;
    // Waiting for the next page to fill
    if (nextPagePending) return true;
    // Current page doesn't have a full set of RECIPE_BATCH_SIZE cards and data is still arriving
    if (currentPageRecipes.length < RECIPE_BATCH_SIZE && (isBuffering || poolInfo.poolSize > recipes.length)) return true;
    return false;
  }, [loading, recipes.length, nextPagePending, currentPageRecipes, isBuffering, poolInfo.poolSize]);

  const listData = useMemo(() => {
    if (isPageLoading) return [];  // empty — full-page loader shown instead
    return currentPageRecipes;
  }, [isPageLoading, currentPageRecipes]);

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
            <Ionicons name="chevron-back" size={18} color={hasPrevPage ? '#2563EB' : '#94A3B8'} />
            <Text className={'text-sm font-semibold ' + (hasPrevPage ? 'text-primary' : 'text-text-muted')}>
              Prev
            </Text>
          </Pressable>

          {/* Page indicator */}
          <View className="items-center">
            <Text className="text-sm font-semibold text-text-primary">
              Page {currentPage + 1}
            </Text>
            {poolInfo.poolSize > 0 ? (
              <Text className="text-xs text-text-muted mt-0.5">
                {poolInfo.shownCount} of {poolInfo.poolSize} recipes
              </Text>
            ) : null}
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
                  ? 'bg-blue-100 border border-blue-200'
                  : 'opacity-30 bg-surface border border-border')
            }
            accessibilityRole="button"
            accessibilityLabel={isLoadingNext ? 'Loading next page' : 'Next page'}
          >
            {isLoadingNext ? (
              <>
                <ActivityIndicator size="small" color="#2563EB" />
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

  return (
    <SafeAreaView className="flex-1 bg-background">
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

      {!hasActiveSession && !loading ? (
        <EmptyState onStart={handleStartSession} />
      ) : isPageLoading && hasActiveSession ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator size="large" color="#2563EB" />
          <Text className="text-sm text-text-secondary mt-3 font-medium">
            Finding great recipes for you…
          </Text>
        </View>
      ) : (
        <FlatList
          data={listData}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          ListHeaderComponent={
            <>
              {error ? (
                <View className="mb-2 py-3 bg-red-50 border border-red-200 rounded-xl flex-row items-center gap-2 px-4">
                  <Ionicons name="warning-outline" size={16} color="#DC2626" />
                  <Text className="text-sm text-red-600 flex-1">{error}</Text>
                </View>
              ) : null}
              {session.sessionPoolId ? (
                <View className="flex-row items-center gap-2 mb-4 py-2 px-3 bg-blue-50 rounded-xl">
                  <Ionicons name="restaurant-outline" size={14} color="#2563EB" />
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
 * Prompt shown when no active session exists yet.
 * @param {object} props
 * @param {function} props.onStart - Called when the user taps "Start Cooking Session".
 */
function EmptyState({ onStart }) {
  return (
    <View className="flex-1 items-center justify-center px-8">
      <View className="w-24 h-24 rounded-full bg-blue-50 items-center justify-center mb-6">
        <Ionicons name="restaurant-outline" size={48} color="#2563EB" />
      </View>
      <Text className="text-2xl font-bold text-text-primary mb-3 text-center">
        What are you cooking today?
      </Text>
      <Text className="text-base text-text-secondary text-center mb-8 leading-6">
        Tell us what ingredients you have and we will find perfect recipes in seconds.
      </Text>
      <Pressable
        onPress={onStart}
        className="bg-primary py-4 px-8 rounded-xl w-full items-center active:opacity-90"
        accessibilityRole="button"
        accessibilityLabel="Start cooking session"
      >
        <Text className="text-white text-base font-semibold">Start Cooking Session</Text>
      </Pressable>
    </View>
  );
}
