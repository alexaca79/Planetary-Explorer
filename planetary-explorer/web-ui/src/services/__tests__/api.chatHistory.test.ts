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
      messages: [{ role: 'user' as const, content: 'Show Toronto in 2026', timestamp: new Date() }],
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

  it('changes memory inclusion using the latest session revision', async () => {
    const session = {
      sessionId: 'saved-1', title: 'Thunder Bay', revision: 7,
      messages: [{ role: 'user', content: 'baseline June 1' }], context: {},
    };
    get.mockResolvedValue({ data: session });
    put.mockResolvedValue({ data: { ...session, memoryEnabled: false } });

    await apiService.setChatSessionMemory('saved-1', false);

    expect(put).toHaveBeenCalledWith('/api/chat-history/sessions/saved-1', expect.objectContaining({
      expectedRevision: 7, memoryEnabled: false, messages: session.messages,
    }));
  });

  it('forwards disabled memory to the query endpoint', async () => {
    post.mockResolvedValue({ data: { response: 'Done' } });

    await apiService.sendChatMessage('baseline', undefined, 'current', [], undefined,
      undefined, undefined, undefined, undefined, undefined, undefined, undefined,
      undefined, undefined, false);

    expect(post).toHaveBeenCalledWith('/api/query', expect.objectContaining({ memory_enabled: false }), expect.anything());
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