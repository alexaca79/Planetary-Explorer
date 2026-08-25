import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getAuthToken, refreshAuthToken } from '../authHelper';
import { apiService } from '../api';

vi.mock('../authHelper', () => ({
  getAuthToken: vi.fn(),
  refreshAuthToken: vi.fn(),
}));

const mockedGetAuthToken = vi.mocked(getAuthToken);
const mockedRefreshAuthToken = vi.mocked(refreshAuthToken);

const streamResponse = (chunks: string[]): Response => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
};

const sendStreamingMessage = (
  handlers: Record<string, (event: any) => void>,
  signal?: AbortSignal,
) => apiService.sendChatMessage(
  'Analyze the map',
  undefined,
  'session-1',
  [],
  undefined,
  true,
  undefined,
  'gpt-4o',
  'none',
  undefined,
  false,
  'public',
  signal,
  handlers,
);

describe('ApiService query streaming', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockedGetAuthToken.mockReset();
    mockedRefreshAuthToken.mockReset();
    mockedGetAuthToken.mockResolvedValue(null);
    mockedRefreshAuthToken.mockResolvedValue(null);
    (apiService as any).api = { defaults: { baseURL: 'https://api.example' } };
  });

  it('parses trace and terminal events split across reader chunks', async () => {
    // Arrange
    const onTrace = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      'data: {"type":"tool_',
      'call","tool":"geofm_list_models"}\n\ndata: {"type":"query_result",',
      '"payload":{"response":"complete"}}\n',
      '\n',
    ])));

    // Act
    const result = await sendStreamingMessage({ onTrace });

    // Assert
    expect(result).toEqual({ response: 'complete' });
    expect(onTrace).toHaveBeenCalledWith({
      type: 'tool_call',
      tool: 'geofm_list_models',
    });
  });

  it('retries one unauthorized stream with the refreshed bearer token', async () => {
    // Arrange
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(streamResponse([
        'data: {"type":"query_result","payload":{"response":"ok"}}\n\n',
      ]));
    vi.stubGlobal('fetch', fetchMock);
    mockedGetAuthToken.mockResolvedValue('expired-token');
    mockedRefreshAuthToken.mockResolvedValue('refreshed-token');

    // Act
    const result = await sendStreamingMessage({});

    // Assert
    expect(result.response).toBe('ok');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1][1]?.headers as Record<string, string>).Authorization)
      .toBe('Bearer refreshed-token');
  });

  it('normalizes a browser AbortError as a cancelled request', async () => {
    // Arrange
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')),
    );

    // Act
    const request = sendStreamingMessage({});

    // Assert
    await expect(request).rejects.toMatchObject({
      name: 'CanceledError',
      cancelled: true,
    });
  });
});