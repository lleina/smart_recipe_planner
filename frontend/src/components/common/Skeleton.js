/**
 * Skeleton loading placeholder.
 * Renders a pulsing placeholder block for loading states.
 */

import { useEffect, useRef } from 'react';
import { Animated, View } from 'react-native';

/**
 * Pulsing placeholder block for loading states.
 * @param {object} props
 * @param {number} [props.width] - Explicit width; omit to use className sizing.
 * @param {number} [props.height] - Explicit height; omit to use className sizing.
 * @param {number} [props.borderRadius=8] - Corner radius.
 * @param {string} [props.className] - Additional NativeWind class names.
 */
export default function Skeleton({ width, height, borderRadius = 8, className: extraClass = '' }) {
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 800, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.3, duration: 800, useNativeDriver: true }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={{ width, height, borderRadius, opacity }}
      className={`bg-gray-200 ${extraClass}`}
    />
  );
}
