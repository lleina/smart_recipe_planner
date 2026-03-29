/**
 * Step indicator for multi-step flows (onboarding, session setup).
 * Shows progress dots with active state.
 */

import { View } from 'react-native';

export default function StepIndicator({ totalSteps, currentStep }) {
  return (
    <View className="flex-row items-center justify-center gap-2 py-4">
      {Array.from({ length: totalSteps }, (_, i) => (
        <View
          key={i}
          className={`h-2 rounded-full ${
            i === currentStep ? 'w-8 bg-primary' : 'w-2 bg-border'
          }`}
        />
      ))}
    </View>
  );
}
