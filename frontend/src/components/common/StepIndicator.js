/**
 * Step indicator for multi-step flows (onboarding, session setup).
 * Shows progress dots with active state.
 */

import { View } from 'react-native';

/**
 * Dot-based step progress indicator for multi-step flows.
 * The active dot is wider than inactive ones to show position at a glance.
 * @param {object} props
 * @param {number} props.totalSteps - Total number of steps.
 * @param {number} props.currentStep - Zero-based index of the current step.
 */
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
