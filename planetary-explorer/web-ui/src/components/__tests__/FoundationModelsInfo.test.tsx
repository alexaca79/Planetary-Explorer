import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import FoundationModelsInfo from '../FoundationModelsInfo';
import { authenticatedFetch } from '../../services/authHelper';

vi.mock('../../services/authHelper', () => ({
  authenticatedFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(authenticatedFetch);

describe('FoundationModelsInfo', () => {
  beforeEach(() => {
    mockedFetch.mockReset();
    mockedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        checks: {
          geospatial_foundation_models: {
            status: 'connected',
            enabled: true,
            connected: true,
            endpoint_host: 'geofm.example',
            tool_count: 4,
            tools: ['geofm_list_models', 'geofm_compare_epochs'],
            models: [{
              profile: 'planaura_hls',
              model_id: 'NRCan/Planaura-1.0',
              model_revision: 'fbbabfdcc0d5e48f7bd05c79b512563cf337742f',
              approval_state: 'conditional',
              supported_collections: ['hls2-s30', 'hls2-l30'],
              geographic_scope: 'Canada',
              license: 'OGL-Canada-2.0',
            }],
          },
        },
      }),
    } as Response);
  });

  it('shows connected foundation model details and analysis capabilities', async () => {
    // Arrange
    render(<FoundationModelsInfo apiBaseUrl="https://api.example" />);

    // Act
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /foundation models/i }));

    // Assert
    expect(screen.getByRole('dialog')).toHaveTextContent('NRCan/Planaura-1.0');
    expect(screen.getByRole('dialog')).toHaveTextContent('Connected');
    expect(screen.getByRole('dialog')).toHaveTextContent('Epoch comparison');
    expect(screen.getByRole('dialog')).toHaveTextContent('hls2-s30, hls2-l30');
  });

  it('contains keyboard focus and restores it when dismissed', async () => {
    // Arrange
    render(<FoundationModelsInfo apiBaseUrl="https://api.example" />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    const trigger = screen.getByRole('button', { name: /foundation models/i });

    // Act
    fireEvent.click(trigger);
    const close = screen.getByRole('button', { name: /close foundation models/i });

    // Assert
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('preserves enabled disconnected details from a degraded health response', async () => {
    // Arrange
    mockedFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({
        checks: {
          geospatial_foundation_models: {
            status: 'degraded',
            enabled: true,
            connected: false,
            endpoint_host: 'geofm.internal.example',
            tool_count: 0,
            tools: [],
            models: [],
          },
        },
      }),
    } as Response);
    render(<FoundationModelsInfo apiBaseUrl="https://api.example" />);

    // Act
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /foundation models/i }));

    // Assert
    expect(screen.getByRole('dialog')).toHaveTextContent('MCP unavailable');
    expect(screen.getByRole('dialog')).toHaveTextContent('geofm.internal.example');
    expect(screen.getByRole('dialog')).not.toHaveTextContent('Not enabled');
  });
});