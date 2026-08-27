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
            tool_count: 5,
            tools: ['geofm_list_models', 'geofm_compare_epochs', 'geofm_retry_run'],
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
    expect(screen.getByRole('dialog')).toHaveTextContent('Run retry');
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

  it('does not report unrelated overall health failures when GeoFM is connected', async () => {
    // Arrange
    mockedFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({
        checks: {
          geospatial_foundation_models: {
            status: 'connected',
            enabled: true,
            connected: true,
            endpoint_host: 'geofm.example',
            tool_count: 5,
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
    expect(screen.getByRole('dialog')).toHaveTextContent('MCP connected');
    expect(screen.getByRole('dialog')).not.toHaveTextContent('unavailable');
  });

  it('renders classification profiles, class schemes, and blocked deployment gates', async () => {
    // Arrange
    mockedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        checks: {
          geospatial_foundation_models: {
            status: 'connected',
            enabled: true,
            connected: true,
            endpoint_host: 'geofm.example',
            tool_count: 7,
            tools: ['geofm_classify_aoi', 'geofm_list_class_schemes'],
            models: [
              {
                profile: 'planaura_classify_s2',
                model_id: 'NRCan/Planaura-1.0',
                model_revision: 'fbbabfdcc0d5e48f7bd05c79b512563cf337742f',
                approval_state: 'conditional',
                supported_collections: ['sentinel-2-l2a'],
                geographic_scope: 'Canada',
                license: 'OGL-Canada-2.0',
                capability: 'classify',
                sensor_family: 'optical',
                classification_mode: 'unsupervised',
                class_scheme_id: 'planaura_unsupervised_v1',
                mandatory_warnings: ['Classes are unsupervised clusters.'],
              },
              {
                profile: 'planaura_classify_s1',
                model_id: 'NRCan/Planaura-1.0',
                model_revision: 'fbbabfdcc0d5e48f7bd05c79b512563cf337742f',
                approval_state: 'blocked',
                supported_collections: ['sentinel-1-rtc'],
                geographic_scope: 'Canada',
                license: 'OGL-Canada-2.0',
                capability: 'classify',
                sensor_family: 'sar',
                classification_mode: 'unsupervised',
                class_scheme_id: 'planaura_sar_surface_v1',
                mandatory_warnings: [],
              },
            ],
            class_schemes: [
              {
                scheme_id: 'planaura_unsupervised_v1',
                version: '1.0.0',
                source: 'PlanAura embedding clusters',
                license: 'OGL-Canada-2.0',
                labels: [
                  {
                    class_value: 1,
                    name: 'Water-like',
                    colour_hex: '#2b6cb0',
                    description: 'High NDWI cluster.',
                  },
                ],
              },
            ],
          },
        },
      }),
    } as Response);
    render(<FoundationModelsInfo apiBaseUrl="https://api.example" />);

    // Act
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /foundation models/i }));

    // Assert
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('Land cover classification');
    expect(dialog).toHaveTextContent('SAR (radar)');
    expect(dialog).toHaveTextContent('planaura_unsupervised_v1 (unsupervised)');
    expect(dialog).toHaveTextContent('OGL-Canada-2.0');
    expect(dialog).toHaveTextContent('Classes are unsupervised clusters.');
    expect(dialog).toHaveTextContent('Not yet available in this deployment');
    expect(dialog).toHaveTextContent('Published class schemes');
    expect(dialog).toHaveTextContent('planaura_unsupervised_v1 v1.0.0');
    expect(dialog).toHaveTextContent('Water-like');
  });
});