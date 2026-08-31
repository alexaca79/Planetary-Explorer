import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MapView from '../MapView';

const analysisResult = {
  result: {
    analysis: 'Canadian 2026 terrain analysis',
    features_identified: ['ridge', 'valley', 'water'],
    imagery_metadata: { source: 'Sentinel-2', date: '2026-08-26' },
  },
};

const apiMocks = vi.hoisted(() => ({
  triggerGeointAnalysis: vi.fn(),
}));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, triggerGeointAnalysis: apiMocks.triggerGeointAnalysis };
});

vi.mock('../../services/authHelper', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/authHelper')>();
  return {
    ...actual,
    authenticatedFetch: vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        azureMaps: {
          subscriptionKey: 'DEVELOPMENT_MODE_NO_KEY',
          developmentMode: true,
        },
      }),
    }),
  };
});

const createMapInstance = () => {
  const instance = {
    events: {
      add: vi.fn((event: string, handler: () => void) => {
        if (event === 'ready') handler();
      }),
      remove: vi.fn(),
    },
    markers: { add: vi.fn(), remove: vi.fn() },
    sources: { add: vi.fn(), remove: vi.fn(), getById: vi.fn() },
    layers: { add: vi.fn(), remove: vi.fn(), getLayerById: vi.fn(), move: vi.fn() },
    setCamera: vi.fn(),
    getCamera: vi.fn().mockReturnValue({ center: [-106.3468, 56.1304], zoom: 3 }),
    setStyle: vi.fn(),
    dispose: vi.fn(),
  };
  return instance;
};

const atlasMock = {
  Map: vi.fn().mockImplementation(function MockMap() {
    return createMapInstance();
  }),
  HtmlMarker: vi.fn().mockImplementation(function MockHtmlMarker(options) {
    return { options, setOptions: vi.fn() };
  }),
  AuthenticationType: { subscriptionKey: 'subscriptionKey' },
  data: { Position: vi.fn((longitude, latitude) => [longitude, latitude]) },
};

const leafletMock = {
  map: vi.fn(),
  marker: vi.fn(),
  icon: vi.fn(),
};

const renderMap = (props: React.ComponentProps<typeof MapView> = { selectedDataset: null }) =>
  render(<MapView selectedDataset={null} {...props} />);

const openModulePicker = async () => {
  const button = await screen.findByTitle('Geointelligence Modules');
  fireEvent.click(button);
  await screen.findByText('Geointelligence Modules');
};

describe('GEOINT module flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.triggerGeointAnalysis.mockResolvedValue(analysisResult);
    (globalThis as any).atlas = atlasMock;
    (globalThis as any).L = leafletMock;
  });

  it('opens the current module picker after the map is ready', async () => {
    renderMap();

    await openModulePicker();

    expect(atlasMock.Map).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ center: [-106.3468, 56.1304], zoom: 3 }),
    );
    expect(screen.getByText('Terrain Analysis')).toBeInTheDocument();
    expect(screen.getByText('Mobility Assessment')).toBeInTheDocument();
    expect(screen.getByText('Resilience')).toBeInTheDocument();
  });

  it('selects terrain and enables its pin workflow in one action', async () => {
    const onGeointAnalysis = vi.fn();
    const onModuleSelected = vi.fn();
    renderMap({ selectedDataset: null, onGeointAnalysis, onModuleSelected });
    await openModulePicker();

    fireEvent.click(screen.getByText('Terrain Analysis'));

    expect(onModuleSelected).toHaveBeenCalledWith('terrain');
    expect(onGeointAnalysis).toHaveBeenCalledWith({
      type: 'module_selected',
      message: '**Terrain selected.**',
    });
    expect(screen.queryByText('Geointelligence Modules')).not.toBeInTheDocument();
  });

  it('places a Canadian pin with the universal drop-pin control', async () => {
    const onPinChange = vi.fn();
    renderMap({ selectedDataset: null, onPinChange });
    const dropPinButton = await screen.findByTitle('Drop Pin: click the map to place a pin and ask any question about that location');
    fireEvent.click(dropPinButton);

    const map = atlasMock.Map.mock.results.at(-1)?.value;
    const clickHandler = await waitFor(() => {
      const handler = map.events.add.mock.calls
        .filter(([event]: [string]) => event === 'click')
        .at(-1)?.[1];
      expect(handler).toBeTypeOf('function');
      return handler;
    });
    act(() => clickHandler({ position: [-79.3832, 43.6532] }));

    await waitFor(() => {
      expect(onPinChange).toHaveBeenCalledWith({ lat: 43.6532, lng: -79.3832 });
    });
  });

  it('selects resilience as a region-scoped chat workflow', async () => {
    const onGeointAnalysis = vi.fn();
    const onModuleSelected = vi.fn();
    renderMap({ selectedDataset: null, onGeointAnalysis, onModuleSelected });
    await openModulePicker();

    fireEvent.click(screen.getByText('Resilience'));

    expect(onModuleSelected).toHaveBeenCalledWith('resilience');
    expect(onGeointAnalysis).not.toHaveBeenCalled();
  });

  it('selects foundation change and arms a bounded AOI pin workflow', async () => {
    const onGeointAnalysis = vi.fn();
    const onModuleSelected = vi.fn();
    const onPinChange = vi.fn();
    renderMap({ selectedDataset: null, onGeointAnalysis, onModuleSelected, onPinChange });
    await openModulePicker();

    fireEvent.click(screen.getByText('Foundation Change'));

    expect(onModuleSelected).toHaveBeenCalledWith('foundation_change');
    expect(onGeointAnalysis).toHaveBeenCalledWith(expect.objectContaining({
      type: 'module_selected',
      message: expect.stringContaining('Click the map to set the analysis area'),
    }));

    const map = atlasMock.Map.mock.results.at(-1)?.value;
    const clickHandler = await waitFor(() => {
      const handler = map.events.add.mock.calls
        .filter(([event]: [string]) => event === 'click')
        .at(-1)?.[1];
      expect(handler).toBeTypeOf('function');
      return handler;
    });
    act(() => clickHandler({ position: [-104.6189, 50.4452] }));

    await waitFor(() => {
      expect(onPinChange).toHaveBeenCalledWith({ lat: 50.4452, lng: -104.6189 });
    });
    await waitFor(() => {
      expect(onGeointAnalysis).toHaveBeenCalledWith(expect.objectContaining({
        type: 'info',
        message: expect.stringContaining('Analysis area set'),
      }));
    });
    expect(apiMocks.triggerGeointAnalysis).not.toHaveBeenCalled();
  });

  it('exposes the current satellite-label control', async () => {
    renderMap();

    expect(await screen.findByTitle('Hide map labels (switch to plain satellite)')).toBeInTheDocument();
  });
});