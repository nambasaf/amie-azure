import React from 'react';
import { Box } from '@mui/material';
import { useInView } from '../hooks/useInView';

/**
 * Wraps children and fades/slides them in when they scroll into view.
 * @param {string} direction - 'up' | 'down' | 'left' | 'right' | 'none'
 * @param {number} delay - ms delay before animation starts
 * @param {number} duration - animation duration in ms
 * @param {number} distance - translate distance in px (for slide)
 */
export default function FadeIn({
  children,
  direction = 'up',
  delay = 0,
  duration = 600,
  distance = 24,
  sx = {},
  ...rest
}) {
  const [ref, isInView] = useInView({ threshold: 0.08, rootMargin: '0px 0px -60px 0px' });

  const getTransform = (visible) => {
    if (!visible) {
      const map = {
        up: `translateY(${distance}px)`,
        down: `translateY(-${distance}px)`,
        left: `translateX(${distance}px)`,
        right: `translateX(-${distance}px)`,
        none: 'none',
      };
      return map[direction];
    }
    return 'none';
  };

  return (
    <Box
      ref={ref}
      sx={{
        opacity: isInView ? 1 : 0,
        transform: getTransform(isInView),
        transition: `opacity ${duration}ms ease-out, transform ${duration}ms ease-out`,
        transitionDelay: `${delay}ms`,
        ...sx,
      }}
      {...rest}
    >
      {children}
    </Box>
  );
}
