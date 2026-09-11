import React, { useState } from 'react';
import { Brain, FolderOpen } from 'lucide-react';

import { apiService, ChatHistorySession, ChatMemoryUsage } from '../services/api';
import './ChatMemory.css';

interface ChatMemorySourcesProps {
  memory?: ChatMemoryUsage;
  busy: boolean;
  onLoad: (session: ChatHistorySession) => boolean | void;
}

export default function ChatMemorySources({ memory, busy, onLoad }: ChatMemorySourcesProps) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!memory?.enabled) return null;
  const sources = Array.isArray(memory.sources)
    ? memory.sources.filter((source, index, all) => (
        typeof source?.sessionId === 'string'
        && typeof source?.title === 'string'
        && all.findIndex((other) => other.sessionId === source.sessionId) === index
      )).slice(0, 4)
    : [];
  if (!memory.earlierTurns && !sources.length && memory.provider !== 'unavailable') return null;

  const openSource = async (sessionId: string) => {
    setOpening(true);
    setError(null);
    try {
      onLoad(await apiService.getChatSession(sessionId));
    } catch {
      setError('This saved chat is unavailable.');
    } finally {
      setOpening(false);
    }
  };

  return (
    <details className="chat-memory-sources">
      <summary><Brain size={14} aria-hidden="true" /> Recalled context</summary>
      {memory.earlierTurns > 0 && <p>Earlier in this chat: {memory.earlierTurns} entries</p>}
      {sources.map((source) => (
        <button
          key={source.sessionId}
          type="button"
          disabled={busy || opening}
          title={`Open saved chat: ${source.title}`}
          onClick={() => void openSource(source.sessionId)}
        >
          <FolderOpen size={14} aria-hidden="true" />
          <span>{source.title}</span>
        </button>
      ))}
      {memory.provider === 'unavailable' && <p>Saved-chat recall is temporarily unavailable.</p>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}