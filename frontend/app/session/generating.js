/**
 * Recipe generation loading screen.
 * Shown after session setup while the pipeline runs.
 * Navigates to discover on success, shows error with retry on failure.
 */

import { useEffect, useRef, useState } from 'react';
import { View, Text, ActivityIndicator, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSession } from '../../src/context/SessionContext';
import { useAuth } from '../../src/context/AuthContext';
import { useRecipeContext } from '../../src/context/RecipeContext';

const STAGES = [
  'Analyzing your ingredients...',
  'Brainstorming recipe ideas...',
  'Finding real recipes...',
  'Ranking the best matches...',
  'Almost ready...',
];

const STAGE_INTERVAL_MS = 4000;

export default function GeneratingScreen() {
  const router = useRouter();
  const { ensureRegistered } = useAuth();
  const { session, getSessionContext, updateSession } = useSession();
  const { recipes, loading, error, startPipeline } = useRecipeContext();
  const [stageIndex, setStageIndex] = useState(0);
  const hasStarted = useRef(false);
  const hasNavigated = useRef(false);

  useEffect(() => {
    if (hasStarted.current) return;
    hasStarted.current = true;

    (async () => {
      // Lazy-register with backend on first server-dependent action
      await ensureRegistered();
      const ctx = getSessionContext();
      startPipeline(ctx);
    })();
  }, []);

  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => {
      setStageIndex((prev) => (prev < STAGES.length - 1 ? prev + 1 : prev));
    }, STAGE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    if (!loading && recipes.length > 0 && !hasNavigated.current) {
      hasNavigated.current = true;
      router.replace('/(tabs)/discover');
    }
  }, [loading, recipes.length, router]);

  const handleRetry = () => {
    setStageIndex(0);
    hasStarted.current = false;
    hasNavigated.current = false;
    const ctx = getSessionContext();
    startPipeline(ctx);
  };

  const handleGoBack = () => {
    router.back();
  };

  if (error && !loading) {
    return (
      <SafeAreaView className="flex-1 bg-background">
        <View className="flex-1 items-center justify-center px-8">
          <View className="w-20 h-20 rounded-full bg-red-50 items-center justify-center mb-6">
            <Ionicons name="alert-circle-outline" size={40} color="#DC2626" />
          </View>
          <Text className="text-xl font-bold text-text-primary mb-2 text-center">
            Something went wrong
          </Text>
          <Text className="text-sm text-text-secondary text-center mb-6 leading-5">
            {error}
          </Text>
          <Pressable
            onPress={handleRetry}
            className="bg-primary py-3.5 px-8 rounded-xl w-full items-center mb-3 active:opacity-90"
            accessibilityRole="button"
            accessibilityLabel="Try again"
          >
            <Text className="text-white text-base font-semibold">Try Again</Text>
          </Pressable>
          <Pressable
            onPress={handleGoBack}
            className="py-3 px-8 rounded-xl w-full items-center active:opacity-70"
            accessibilityRole="button"
            accessibilityLabel="Go back to session setup"
          >
            <Text className="text-sm font-medium text-text-secondary">Back to Setup</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="flex-1 items-center justify-center px-8">
        <View className="w-24 h-24 rounded-full bg-blue-50 items-center justify-center mb-8">
          <ActivityIndicator size="large" color="#2563EB" />
        </View>
        <Text className="text-2xl font-bold text-text-primary mb-3 text-center">
          Finding recipes just for you
        </Text>
        <Text className="text-base text-text-secondary text-center mb-8 leading-6">
          {STAGES[stageIndex]}
        </Text>
        <View className="flex-row items-center gap-1.5">
          {STAGES.map((_, i) => (
            <View
              key={i}
              className={'w-2 h-2 rounded-full ' + (i <= stageIndex ? 'bg-primary' : 'bg-gray-200')}
            />
          ))}
        </View>
      </View>
    </SafeAreaView>
  );
}
