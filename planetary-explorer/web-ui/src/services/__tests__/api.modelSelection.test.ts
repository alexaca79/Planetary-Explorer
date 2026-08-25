import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiService } from '../api';

describe('ApiService model selection', () => {
  const post = vi.fn();

  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ status: 200, data: { response: 'ok' } });
    (apiService as any).api = { post };
  });

  it('serializes the selected model, thinking level, and GEOINT module', async () => {
    // Act
    await apiService.sendChatMessage(
      'Compare the loaded HLS epochs',
      undefined,
      'session-1',
      [],
      undefined,
      true,
      undefined,
      'gpt-5.6-terra',
      'high',
      'foundation_change',
      false,
      'public',
    );

    // Assert
    expect(post).toHaveBeenCalledWith(
      '/api/query',
      expect.objectContaining({
        query: 'Compare the loaded HLS epochs',
        model: 'gpt-5.6-terra',
        reasoning_effort: 'high',
        geoint_module: 'foundation_change',
      }),
      { signal: undefined },
    );
  });
});