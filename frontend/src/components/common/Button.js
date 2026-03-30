/**
 * Reusable button component with primary, secondary, and outline variants.
 */

import { Pressable, Text, ActivityIndicator } from 'react-native';

const VARIANTS = {
  primary: {
    container: 'bg-primary active:bg-primary-dark',
    text: 'text-white',
  },
  secondary: {
    container: 'bg-secondary active:opacity-80',
    text: 'text-white',
  },
  outline: {
    container: 'border border-border bg-surface active:bg-gray-50',
    text: 'text-text-primary',
  },
};

/**
 * Themed button with primary, secondary, and outline variants.
 * @param {object} props
 * @param {string} props.title - Button label text.
 * @param {function} props.onPress - Tap handler.
 * @param {'primary'|'secondary'|'outline'} [props.variant='primary'] - Visual style.
 * @param {boolean} [props.disabled=false] - Prevents interaction when true.
 * @param {boolean} [props.loading=false] - Shows ActivityIndicator instead of label.
 * @param {string} [props.className] - Additional NativeWind class names.
 */
export default function Button({
  title,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  className: extraClass = '',
}) {
  const styles = VARIANTS[variant] || VARIANTS.primary;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      className={`py-4 rounded-xl items-center ${styles.container} ${
        disabled ? 'opacity-50' : ''
      } ${extraClass}`}
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled }}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'outline' ? '#1E293B' : '#FFFFFF'} />
      ) : (
        <Text className={`text-base font-semibold ${styles.text}`}>{title}</Text>
      )}
    </Pressable>
  );
}
