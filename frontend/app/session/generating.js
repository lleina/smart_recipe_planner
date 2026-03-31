/**
 * Recipe generation loading screen.
 * Shown after session setup while the pipeline runs.
 * Navigates to discover on success, shows error with retry on failure.
 *
 * Delivery-tracker style: polls /api/recommend/status every 1.2 s and
 * shows real pipeline stages (brainstorm → search → rank → ready).
 */

import { useEffect, useRef, useState } from 'react';
import { View, Text, ActivityIndicator, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSession } from '../../src/context/SessionContext';
import { useAuth } from '../../src/context/AuthContext';
import { useRecipeContext } from '../../src/context/RecipeContext';
import { getPipelineStatus } from '../../src/services/pipelineService';

const PIPELINE_STEPS = [
  { step: 1, icon: 'bulb-outline',    label: 'Brainstorming recipe ideas',    verb: 'Thinking'  },
  { step: 2, icon: 'search-outline',  label: 'Searching the web for recipes', verb: 'Searching' },
  { step: 3, icon: 'star-outline',    label: 'Ranking the best matches',      verb: 'Ranking'   },
  { step: 4, icon: 'checkmark-circle-outline', label: 'Recipes ready!',        verb: 'Done'      },
];

const POLL_INTERVAL_MS = 1200;

export default function GeneratingScreen() {
  const router = useRouter();
  const { ensureRegistered } = useAuth();
  const { getSessionContext } = useSession();
  const { recipes, loading, error, startPipeline } = useRecipeContext();
  const [pipelineStatus, setPipelineStatus] = useState({ step: 0, label: '', detail: '', total_steps: 4 });
  const hasStarted = useRef(false);
  const hasNavigated = useRef(false);
  const didStartLoading = useRef(false);
  const pollRef = useRef(null);

  /** Clears the polling interval if one is active. */
  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => {
    if (hasStarted.current) return;
    hasStarted.current = true;

    (async () => {
      await ensureRegistered();
      const ctx = getSessionContext();
      startPipeline(ctx);
    })();
  }, []);

  // Track that our pipeline actually started loading
  useEffect(() => {
    if (loading) {
      didStartLoading.current = true;
    }
  }, [loading]);

  // Poll pipeline status while loading
  useEffect(() => {
    if (!loading) {
      stopPolling();
      return;
    }

    const poll = async () => {
      try {
        const status = await getPipelineStatus();
        if (status && typeof status.step === 'number') {
          setPipelineStatus(status);
        }
      } catch {
        // Silently ignore — status is a nice-to-have
      }
    };

    poll(); // immediate first call
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return stopPolling;
  }, [loading]);

  // Navigate only once the NEW pipeline has completed
  useEffect(() => {
    if (
      didStartLoading.current &&
      !loading &&
      recipes.length > 0 &&
      !hasNavigated.current
    ) {
      hasNavigated.current = true;
      router.replace('/(tabs)/discover');
    }
  }, [loading, recipes.length, router]);

  /** Resets all pipeline state and restarts the generation flow. */
  const handleRetry = () => {
    setPipelineStatus({ step: 0, label: '', detail: '', total_steps: 4 });
    hasStarted.current = false;
    hasNavigated.current = false;
    didStartLoading.current = false;
    const ctx = getSessionContext();
    startPipeline(ctx);
  };

  /** Returns to the session setup screen. */
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

  const currentStep = pipelineStatus.step;

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="flex-1 justify-center px-8">

        {/* Header */}
        <Text className="text-2xl font-bold text-text-primary mb-8 text-center">
          Finding recipes for you
        </Text>

        {/* Delivery-tracker steps */}
        <View className="mb-10">
          {PIPELINE_STEPS.map((s, idx) => {
            const isDone    = currentStep > s.step;
            const isActive  = currentStep === s.step;
            const isPending = currentStep < s.step;

            return (
              <View key={s.step}>
                {/* Step row */}
                <View className="flex-row items-center">
                  {/* Icon / indicator */}
                  <View className={'w-10 h-10 rounded-full items-center justify-center mr-4 ' + (
                    isDone   ? 'bg-green-100' :
                    isActive ? 'bg-green-100' :
                               'bg-gray-100'
                  )}>
                    {isDone ? (
                      <Ionicons name="checkmark" size={20} color="#214130" />
                    ) : isActive ? (
                      <ActivityIndicator size="small" color="#214130" />
                    ) : (
                      <Ionicons name={s.icon} size={18} color="#CBD5E1" />
                    )}
                  </View>

                  {/* Label + detail */}
                  <View className="flex-1">
                    <Text className={'text-base ' + (
                      isDone   ? 'text-text-secondary line-through' :
                      isActive ? 'font-semibold text-text-primary' :
                                 'text-text-secondary'
                    )}>
                      {s.label}
                    </Text>
                    {isActive && pipelineStatus.detail ? (
                      <Text className="text-xs text-primary mt-0.5">
                        {pipelineStatus.detail}
                      </Text>
                    ) : null}
                  </View>
                </View>

                {/* Connector line (not after last step) */}
                {idx < PIPELINE_STEPS.length - 1 ? (
                  <View className={'w-0.5 h-6 ml-5 my-0.5 ' + (
                    currentStep > s.step ? 'bg-green-300' : 'bg-gray-200'
                  )} />
                ) : null}
              </View>
            );
          })}
        </View>

      </View>
    </SafeAreaView>
  );
}
