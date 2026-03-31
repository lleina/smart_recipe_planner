/**
 * Step indicator for multi-step flows (onboarding, session setup).
 *
 * Renders a full-width horizontal track with:
 *   • a filled primary-coloured segment proportional to progress
 *   • a numbered circle at the current position
 *   • an optional step-name label below the track
 *
 * The circle divides the track into filled (left) and unfilled (right) halves.
 * Conditional renders prevent zero-width flex children on the first / last step.
 *
 * @param {object}  props
 * @param {number}  props.totalSteps   - Total number of steps in the flow.
 * @param {number}  props.currentStep  - Zero-based index of the active step.
 * @param {string}  [props.label]      - Optional step name shown below the track.
 */

import { View, Text } from 'react-native';

export default function StepIndicator({ totalSteps, currentStep, label }) {
  const leftFlex = currentStep;
  const rightFlex = totalSteps - 1 - currentStep;

  return (
    <View className="px-6 pt-5 pb-3">
      <View className="flex-row items-center">
        {/* Filled track to the left of the circle (hidden on step 0) */}
        {leftFlex > 0 ? (
          <View className="h-0.5 bg-primary" style={{ flex: leftFlex }} />
        ) : null}

        {/* Numbered step circle */}
        <View className="w-8 h-8 rounded-full bg-primary items-center justify-center flex-shrink-0">
          <Text className="text-white text-sm font-bold">{currentStep + 1}</Text>
        </View>

        {/* Unfilled track to the right of the circle (hidden on last step) */}
        {rightFlex > 0 ? (
          <View className="h-0.5 bg-border" style={{ flex: rightFlex }} />
        ) : null}
      </View>

      {label ? (
        <Text className="text-center text-sm text-text-muted mt-2 font-medium">{label}</Text>
      ) : null}
    </View>
  );
}
