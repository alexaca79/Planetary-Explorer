import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import MapView from '../MapView';

// Report development mode so MapView finishes configuration without a live
// Azure Maps key and falls through to the Leaflet fallback.
vi.mock('../../services/authHelper', () => ({
  authenticatedFetch: vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      azureMaps: { subscriptionKey: 'DEVELOPMENT_MODE_NO_KEY', developmentMode: true },
    }),
  }),
  getAccessToken: vi.fn().mockResolvedValue(null),
}));

/**
 * Classification module selection.
 *
 * Classification is chat-driven like Foundation Change: selecting it must not
 * enable pin mode, and the confirmation it sends to chat must state the honest
 * limits of the results before the user submits billed GPU work.
 */

// Azure Maps is deliberately absent so MapView falls back to its built-in
// Leaflet map, which is what lets the modules panel render in jsdom.
const openModulesMenu = async (container: HTMLElement): Promise<void> => {
  const moduleButton = await waitFor(
    () => {
      const button = container.querySelector('[title="Geointelligence Modules"]');
      expect(button).toBeInTheDocument();
      return button as HTMLElement;
    },
    { timeout: 10000 }
  );
  fireEvent.click(moduleButton);
};

describe('Classification module selection', () => {
  beforeEach(() => {
    delete (globalThis as any).atlas;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  }, 15000);

  it('offers a Classification card in the modules panel', async () => {
    // Arrange
    const { container } = render(<MapView selectedDataset={null} onGeointAnalysis={vi.fn()} />);

    // Act
    await openModulesMenu(container);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('Classification')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/PlanAura land-cover clusters from Sentinel-1, -2 and -3 scenes/i)
    ).toBeInTheDocument();
  }, 15000);

  it('notifies chat with the sensor requirements and honest limits when selected', async () => {
    // Arrange
    const onGeointAnalysis = vi.fn();
    const onModuleSelected = vi.fn();
    const { container } = render(
      <MapView selectedDataset={null} onGeointAnalysis={onGeointAnalysis} onModuleSelected={onModuleSelected} />
    );
    await openModulesMenu(container);

    // Act
    await waitFor(() => screen.getByText('Classification'));
    fireEvent.click(screen.getByText('Classification'));

    // Assert
    expect(onModuleSelected).toHaveBeenCalledWith('classification');
    const notification = onGeointAnalysis.mock.calls
      .map(([event]) => event)
      .find((event) => event.type === 'module_selected');
    expect(notification).toBeDefined();
    expect(notification.message).toContain('Classification selected.');
    expect(notification.message).toContain('Sentinel-2');
    expect(notification.message).toContain('Sentinel-1 RTC');
    expect(notification.message).toContain('unsupervised');
    expect(notification.message).toContain('confidence');
    expect(notification.message).toContain('approval');
  }, 15000);

  it('does not enable pin mode, because the AOI comes from the map bounds', async () => {
    // Arrange
    const onPinChange = vi.fn();
    const { container } = render(
      <MapView selectedDataset={null} onGeointAnalysis={vi.fn()} onPinChange={onPinChange} />
    );
    await openModulesMenu(container);

    // Act
    await waitFor(() => screen.getByText('Classification'));
    fireEvent.click(screen.getByText('Classification'));

    // Assert
    expect(container.querySelector('[title*="Pin mode active"]')).toBeNull();
    expect(onPinChange).not.toHaveBeenCalled();
  }, 15000);
});
