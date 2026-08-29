import '@testing-library/jest-dom';

class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = globalThis.ResizeObserver || (MockResizeObserver as unknown as typeof ResizeObserver);
