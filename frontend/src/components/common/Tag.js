/**
 * Selectable tag component for multi-select lists (cuisines, dietary, equipment).
 */

import { Pressable, Text } from 'react-native';

export default function Tag({ label, selected, onPress, variant = 'default' }) {
  const baseStyle = 'px-4 py-2 rounded-full border mr-2 mb-2';
  const selectedStyle = 'bg-primary border-primary';
  const unselectedStyle = 'bg-surface border-border';

  const urgentStyle = variant === 'urgent'
    ? 'border-danger bg-red-50'
    : '';

  return (
    <Pressable
      onPress={onPress}
      className={`${baseStyle} ${selected ? selectedStyle : unselectedStyle} ${urgentStyle}`}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
    >
      <Text
        className={`text-sm font-medium ${
          selected ? 'text-white' : 'text-text-primary'
        }`}
      >
        {label}
      </Text>
    </Pressable>
  );
}
