/**
 * Numeric stepper control for serving count selection.
 */

import { View, Text, Pressable } from 'react-native';

export default function Stepper({ value, onValueChange, min = 1, max = 12, label }) {
  const decrement = () => {
    if (value > min) onValueChange(value - 1);
  };

  const increment = () => {
    if (value < max) onValueChange(value + 1);
  };

  return (
    <View className="flex-row items-center justify-between">
      {label && <Text className="text-base text-text-primary font-medium">{label}</Text>}
      <View className="flex-row items-center gap-4">
        <Pressable
          onPress={decrement}
          disabled={value <= min}
          className={`w-10 h-10 rounded-full items-center justify-center border border-border ${
            value <= min ? 'opacity-30' : 'active:bg-gray-100'
          }`}
          accessibilityRole="button"
          accessibilityLabel={`Decrease ${label || 'value'}`}
        >
          <Text className="text-lg text-text-primary font-bold">-</Text>
        </Pressable>

        <Text className="text-xl font-semibold text-text-primary w-8 text-center">
          {value}
        </Text>

        <Pressable
          onPress={increment}
          disabled={value >= max}
          className={`w-10 h-10 rounded-full items-center justify-center border border-border ${
            value >= max ? 'opacity-30' : 'active:bg-gray-100'
          }`}
          accessibilityRole="button"
          accessibilityLabel={`Increase ${label || 'value'}`}
        >
          <Text className="text-lg text-text-primary font-bold">+</Text>
        </Pressable>
      </View>
    </View>
  );
}
