import {
  ChatHistorySession,
  ChatHistorySnapshot,
  ChatMessage,
} from '../services/api';

export function createChatHistorySaveQueue(
  save: (
    sessionId: string,
    snapshot: ChatHistorySnapshot,
  ) => Promise<ChatHistorySession>,
): (sessionId: string, snapshot: ChatHistorySnapshot) => Promise<ChatHistorySession> {
  let tail: Promise<void> = Promise.resolve();
  return (sessionId, snapshot) => {
    const request = tail.then(
      () => save(sessionId, snapshot),
      () => save(sessionId, snapshot),
    );
    tail = request.then(
      () => undefined,
      () => undefined,
    );
    return request;
  };
}

export function persistedChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => !message.isThinking);
}

export function chatHistoryFingerprint(snapshot: ChatHistorySnapshot): string {
  return JSON.stringify(snapshot);
}

export function restoreChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    ...message,
    timestamp: new Date(message.timestamp),
    isThinking: false,
  }));
}