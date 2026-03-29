/**
 * Recipe discovery screen - main recipe feed.
 * Shows recipe cards, handles load more, and tracks session state.
 */

import { useEffect, useRef, useState } from 'react';
import { View, Text, ScrollView, Pressable, Modal, FlatList } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useSession } from '../../src/context/SessionContext';
import { useAuth } from '../../src/context/AuthContext';
import useRecipes from '../../src/hooks/useRecipes';
import useSavedRecipes from '../../src/hooks/useSavedRecipes';
import RecipeCard from '../../src/components/common/RecipeCard';
import { RECIPE_BATCH_SIZE } from '../../src/constants/config';

const SURPRISE_INTERVAL = 10;
const FATIGUE_THRESHOLD = 7;

export default function DiscoverScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { session, updateSession, resetSession, getSessionContext } = useSession();
  const { recipes, loading, error, poolInfo, startPipeline, loadNextBatch, rerank } = useRecipes();
  const { save, remove, isSaved, savedRecipes } = useSavedRecipes();
  const [refreshCount, setRefreshCount] = useState(0);
  const [showFatiguePrompt, setShowFatiguePrompt] = useState(false);
  const [showSavedPanel, setShowSavedPanel] = useState(false);
  const hasStartedRef = useRef(false);

  useEffect(() => {
    console.log('[Discover] Session state:', {
      sessionReady: session.sessionReady,
      hasStarted: hasStartedRef.current,
      loading,
      userId: user?.id,
    });
    if (session.sessionReady && !hasStartedRef.current && !loading) {
      console.log('[Discover] Starting pipeline with context:', getSessionContext());
      hasStartedRef.current = true;
      startPipeline(getSessionContext());
      updateSession({ sessionReady: false });
    }
  }, [session.sessionReady, loading, startPipeline, getSessionContext, updateSession]);

  const handleStartSession = () => {
    resetSession();
    hasStartedRef.current = false;
    router.push('/session/setup');
  };

  const handleLoadMore = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setRefreshCount((c) => {
      const next = c + 1;
      if (next >= FATIGUE_THRESHOLD && recipes.length > 0) {
        setShowFatiguePrompt(true);
      }
      return next;
    });
    await loadNextBatch();
  };

  const handleSave = async (recipe) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    const saved = isSaved(recipe.id);
    if (saved) {
      const entry = savedRecipes.find((s) => s.recipeId === recipe.id);
      if (entry) remove(entry.id);
    } else {
      await save(recipe.id, session.sessionPoolId);
      await rerank(recipe.id, 'saved');
    }
  };

  const getBadge = (recipe, index) => {
    const totalShown = (poolInfo.shownCount - recipes.length) + index;
    if (totalShown > 0 && totalShown % SURPRISE_INTERVAL === 0) return 'Try Something New';
    if (recipe.totalTime != null && recipe.totalTime <= 20) return 'Quick';
    return null;
  };

  const hasActiveSession = session.sessionPoolId != null || recipes.length > 0 || loading;

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
          <Pressable
            onPress={() => setShowSavedPanel(true)}
            className="w-10 h-10 items-center justify-center"
            accessibilityLabel="View saved recipes"
          >
            <Ionicons name="bookmark-outline" size={24} color="#1E293B" />
          </Pressable>
        </View>
      </View>

      {error ? (
        <View className="mx-6 mb-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl flex-row items-center gap-2">
          <Ionicons name="warning-outline" size={16} color="#DC2626" />
          <Text className="text-sm text-red-600 flex-1">{error}</Text>
        </View>
      ) : null}

      {!hasActiveSession && !loading ? (
        <EmptyState onStart={handleStartSession} />
      ) : (
        <ScrollView
          className="flex-1 px-6"
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        >
          {session.sessionPoolId ? (
            <View className="flex-row items-center gap-2 mb-4 py-2 px-3 bg-blue-50 rounded-xl">
              <Ionicons name="restaurant-outline" size={14} color="#2563EB" />
              <Text className="text-xs font-medium text-primary capitalize">
                {session.mealType} · {session.servingCount} serving{session.servingCount !== 1 ? 's' : ''}
                {session.occasion ? ' · ' + session.occasion : ''}
              </Text>
            </View>
          ) : null}

          {showFatiguePrompt ? (
            <View className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-2xl">
              <Text className="text-sm font-semibold text-amber-800 mb-1">Having trouble deciding?</Text>
              <Text className="text-sm text-amber-700 mb-3">Let us help you narrow it down.</Text>
              <Pressable
                onPress={() => { setShowFatiguePrompt(false); handleStartSession(); }}
                className="bg-amber-600 px-4 py-2 rounded-lg self-start"
              >
                <Text className="text-white text-sm font-semibold">Refine Preferences</Text>
              </Pressable>
            </View>
          ) : null}

          {loading && recipes.length === 0
            ? Array.from({ length: RECIPE_BATCH_SIZE }).map((_, i) => (
                <RecipeCard key={'sk-' + i} loading />
              ))
            : recipes.map((recipe, index) => (
                <RecipeCard
                  key={recipe.id}
                  recipe={recipe}
                  isSaved={isSaved(recipe.id)}
                  badge={getBadge(recipe, index)}
                  onPress={() => router.push('/recipe/' + recipe.id)}
                  onSave={() => handleSave(recipe)}
                />
              ))}

          {loading && recipes.length > 0
            ? Array.from({ length: RECIPE_BATCH_SIZE }).map((_, i) => (
                <RecipeCard key={'ld-' + i} loading />
              ))
            : null}

          {!loading && recipes.length > 0 ? (
            <Pressable
              onPress={handleLoadMore}
              className="py-4 rounded-xl border border-border items-center flex-row justify-center gap-2 active:bg-gray-50"
            >
              <Ionicons name="chevron-down" size={18} color="#64748B" />
              <Text className="text-sm font-semibold text-text-secondary">Load More Recipes</Text>
            </Pressable>
          ) : null}

          {poolInfo.poolSize > 0 ? (
            <Text className="text-xs text-text-muted text-center mt-3">
              {poolInfo.shownCount} of {poolInfo.poolSize} recipes shown
            </Text>
          ) : null}
        </ScrollView>
      )}

      <SavedPanel
        visible={showSavedPanel}
        onClose={() => setShowSavedPanel(false)}
        savedRecipes={savedRecipes}
      />
    </SafeAreaView>
  );
}

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

function SavedPanel({ visible, onClose, savedRecipes }) {
  const router = useRouter();
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView className="flex-1 bg-background">
        <View className="px-6 pt-4 pb-2 flex-row items-center justify-between border-b border-border">
          <Text className="text-xl font-bold text-text-primary">Saved Recipes</Text>
          <Pressable onPress={onClose} accessibilityLabel="Close">
            <Ionicons name="close" size={24} color="#64748B" />
          </Pressable>
        </View>
        {savedRecipes.length === 0 ? (
          <View className="flex-1 items-center justify-center px-8">
            <Ionicons name="bookmark-outline" size={48} color="#94A3B8" />
            <Text className="text-base text-text-secondary mt-4 text-center">
              No saved recipes yet. Tap the bookmark icon on any card.
            </Text>
          </View>
        ) : (
          <FlatList
            data={savedRecipes}
            keyExtractor={(item) => item.id}
            contentContainerStyle={{ padding: 24 }}
            renderItem={({ item }) => (
              <Pressable
                onPress={() => { onClose(); router.push('/recipe/' + item.recipeId); }}
                className="flex-row items-center py-3 border-b border-border active:bg-gray-50"
              >
                <View className="flex-1">
                  <Text className="text-sm font-semibold text-text-primary" numberOfLines={1}>
                    {item.recipeTitle || item.recipeId}
                  </Text>
                  <Text className="text-xs text-text-muted mt-0.5">
                    Saved {item.savedAt ? new Date(item.savedAt).toLocaleDateString() : ''}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color="#94A3B8" />
              </Pressable>
            )}
          />
        )}
      </SafeAreaView>
    </Modal>
  );
}
