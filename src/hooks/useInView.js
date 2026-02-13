import { useState, useEffect, useRef } from 'react';

const defaultOptions = {
  root: null,
  rootMargin: '0px 0px -80px 0px',
  threshold: 0.1,
};

/**
 * Hook that returns whether the element ref is in view (IntersectionObserver).
 * @param {Object} options - IntersectionObserver options (root, rootMargin, threshold)
 * @returns {[React.RefObject, boolean]} [ref, isInView]
 */
export function useInView(options = {}) {
  const [isInView, setIsInView] = useState(false);
  const ref = useRef(null);
  const opts = { ...defaultOptions, ...options };

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(([entry]) => {
      setIsInView(entry.isIntersecting);
    }, opts);

    observer.observe(el);
    return () => observer.disconnect();
  }, [opts.root, opts.rootMargin, opts.threshold]);

  return [ref, isInView];
}

export default useInView;
