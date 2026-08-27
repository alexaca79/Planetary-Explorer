import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiService } from '../api';

describe('ApiService chat history', () => {
  const get = vi.fn();
  const put = vi.fn();
  const post = vi.fn();

  beforeEach(() => {
    get.mockReset();
    put.mockReset();
    post.mockReset();
    (apiService as any).api = { get, post, put };
  });

  it('saves a session snapshot to the encoded session route', async () => {
    // Arrange
    const snapshot = {
      expectedRevision: 0,
      mutationId: 'frontend-api-save',
      messages: [{ role: 'user' as const, content: 'Show Seattle', timestamp: new Date() }],
      context: { selectedModel: 'gpt-5' },
    };
    put.mockResolvedValue({ data: { sessionId: 'session/one', ...snapshot } });

    // Act
    await apiService.saveChatSession('session/one', snapshot);

    // Assert
    expect(put).toHaveBeenCalledWith(
      '/api/chat-history/sessions/session%2Fone',
      snapshot,
    );
  });

  it('requests an exported session as a blob', async () => {
    // Arrange
    const archive = new Blob(['zip']);
    get.mockResolvedValue({ data: archive });

    // Act
    const result = await apiService.exportChatSession('session-1');

    // Assert
    expect(get).toHaveBeenCalledWith(
      '/api/chat-history/sessions/session-1/export',
      { responseType: 'blob' },
    );
    expect(result).toBe(archive);
  });

  it('clears the JSON content type for multipart file uploads', async () => {
    // Arrange
    const file = new File(['lat,lng\n'], 'coordinates.csv', { type: 'text/csv' });
    post.mockResolvedValue({ data: { id: 'file-1', name: file.name } });

    // Act
    await apiService.uploadChatFile('session-1', file);

    // Assert
    expect(post).toHaveBeenCalledWith(
      '/api/chat-history/sessions/session-1/files',
      expect.any(FormData),
      { headers: { 'Content-Type': undefined } },
    );
  });

  it('forwards restored Pro mode to direct vision requests', async () => {
    // Arrange
    post.mockResolvedValue({ data: { result: { response: 'sampled' }, session_id: 'vision-1' } });

    // Act
    await apiService.sendVisionChatMessage(
      null,
      'What is the elevation?',
      47.5,
      -122.0,
      undefined,
      {
        stac_mode: 'pro',
        current_collection: 'private-dem',
        stac_items: [{ id: 'private-item', collection: 'private-dem', assets: {} }],
      },
    );

    // Assert
    expect(post).toHaveBeenCalledWith(
      '/api/geoint/vision',
      expect.objectContaining({ stac_mode: 'pro' }),
    );
  });
});