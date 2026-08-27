import { describe, expect, it, vi } from 'vitest';

import { ChatHistorySession, ChatHistorySnapshot } from '../../services/api';
import {
  chatHistoryFingerprint,
  createChatHistorySaveQueue,
  restoreChatMessages,
} from '../chatHistory';

describe('chat history snapshots', () => {
  it('changes the autosave fingerprint when only context changes', () => {
    // Arrange
    const base: ChatHistorySnapshot = {
      messages: [{ role: 'user', content: 'Show Seattle', timestamp: new Date(0) }],
      context: { selectedModel: 'gpt-5', stacMode: 'public' },
    };
    const changed: ChatHistorySnapshot = {
      ...base,
      context: { ...base.context, stacMode: 'pro' },
    };

    // Act & Assert
    expect(chatHistoryFingerprint(base)).not.toBe(chatHistoryFingerprint(changed));
  });

  it('restores message timestamps as Date values and clears thinking state', () => {
    // Act
    const restored = restoreChatMessages([
      {
        role: 'assistant',
        content: 'Saved answer',
        timestamp: '2026-08-26T12:00:00Z' as unknown as Date,
        isThinking: true,
      },
    ]);

    // Assert
    expect(restored[0].timestamp).toBeInstanceOf(Date);
    expect(restored[0].isThinking).toBe(false);
  });

  it('serializes saves so an older request cannot finish after a newer request', async () => {
    // Arrange
    let finishFirst!: (session: ChatHistorySession) => void;
    const save = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<ChatHistorySession>((resolve) => {
          finishFirst = resolve;
        }),
      )
      .mockResolvedValue({ clientRevision: 2 } as ChatHistorySession);
    const enqueue = createChatHistorySaveQueue(save);
    const first = enqueue('session-1', {
      clientRevision: 1,
      messages: [],
      context: {},
    });
    const second = enqueue('session-1', {
      clientRevision: 2,
      messages: [],
      context: {},
    });

    // Act
    await Promise.resolve();
    expect(save).toHaveBeenCalledTimes(1);
    finishFirst({ clientRevision: 1 } as ChatHistorySession);
    await first;
    await second;

    // Assert
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls.map((call) => call[1].clientRevision)).toEqual([1, 2]);
  });
});