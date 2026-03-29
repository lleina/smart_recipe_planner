/**
 * Skeleton loading placeholder.
 * Renders a pulsing placeholder block for loading states.
 */

import { useEffect, useRef } from 'react';
import { Animated, View } from 'react-native';

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
