import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiService, ChatHistorySession, ChatMemoryUsage } from '../../services/api';
import ChatMemorySources from '../ChatMemorySources';

const memory: ChatMemoryUsage = {
  enabled: true, provider: 'azure-search', earlierTurns: 2,
  sources: [{ sessionId: 'saved-1', title: 'Thunder Bay baseline', turn: 0, updatedAt: '2026-09-10T00:00:00Z' }],
};

describe('ChatMemorySources', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows recalled context and opens the original saved chat', async () => {
    const session = { sessionId: 'saved-1', messages: [] } as unknown as ChatHistorySession;
    vi.spyOn(apiService, 'getChatSession').mockResolvedValue(session);
    const onLoad = vi.fn();
    render(<ChatMemorySources memory={memory} busy={false} onLoad={onLoad} />);

    fireEvent.click(screen.getByText('Recalled context'));
    fireEvent.click(screen.getByRole('button', { name: 'Thunder Bay baseline' }));

    expect(screen.getByText('Earlier in this chat: 2 entries')).toBeInTheDocument();
    await waitFor(() => expect(onLoad).toHaveBeenCalledWith(session));
  });

  it('does not claim memory recall when memory is disabled', () => {
    const { container } = render(<ChatMemorySources memory={{ ...memory, enabled: false }} busy={false} onLoad={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('prevents opening sources while a turn or save is pending', () => {
    render(<ChatMemorySources memory={memory} busy onLoad={vi.fn()} />);
    fireEvent.click(screen.getByText('Recalled context'));

    expect(screen.getByRole('button', { name: 'Thunder Bay baseline' })).toBeDisabled();
  });
});