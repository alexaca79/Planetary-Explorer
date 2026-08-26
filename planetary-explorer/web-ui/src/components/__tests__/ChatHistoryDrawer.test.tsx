import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiService, ChatHistorySession } from '../../services/api';
import ChatHistoryDrawer from '../ChatHistoryDrawer';

function renderDrawer(onLoad = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ChatHistoryDrawer
        activeSessionId="session-2"
        enabled
        open
        onClose={vi.fn()}
        onLoad={onLoad}
      />
    </QueryClientProvider>,
  );
  return onLoad;
}

describe('ChatHistoryDrawer', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('lists and restores a saved session', async () => {
    // Arrange
    const session: ChatHistorySession = {
      sessionId: 'session-1',
      schemaVersion: 1,
      title: 'Seattle flood scan',
      createdAt: '2026-08-26T12:00:00Z',
      updatedAt: '2026-08-26T12:01:00Z',
      messageCount: 2,
      attachments: [],
      messages: [
        { role: 'user', content: 'Show Seattle flooding', timestamp: new Date('2026-08-26T12:00:00Z') },
        { role: 'assistant', content: 'Loaded one scene', timestamp: new Date('2026-08-26T12:01:00Z') },
      ],
      context: { selectedModel: 'gpt-5' },
    };
    vi.spyOn(apiService, 'listChatSessions').mockResolvedValue([session]);
    vi.spyOn(apiService, 'getChatSession').mockResolvedValue(session);
    const onLoad = renderDrawer();

    // Act
    await screen.findByText('Seattle flood scan');
    fireEvent.click(screen.getByRole('button', { name: 'Open Seattle flood scan' }));

    // Assert
    await waitFor(() => expect(onLoad).toHaveBeenCalledWith(session));
  });

  it('renders a structured upload error without crashing', async () => {
    // Arrange
    const currentSession: ChatHistorySession = {
      sessionId: 'session-2',
      schemaVersion: 1,
      title: 'Current test',
      createdAt: '2026-08-26T12:00:00Z',
      updatedAt: '2026-08-26T12:01:00Z',
      messageCount: 1,
      attachments: [],
      messages: [{ role: 'user', content: 'Test', timestamp: new Date() }],
      context: {},
    };
    vi.spyOn(apiService, 'listChatSessions').mockResolvedValue([currentSession]);
    vi.spyOn(apiService, 'uploadChatFile').mockRejectedValue({
      response: { data: { detail: [{ msg: 'Field required' }] } },
    });
    renderDrawer();
    expect(await screen.findByRole('region', { name: 'Current saved session' }))
      .toHaveTextContent('Current test');

    // Act
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(['x'], 'test.csv', { type: 'text/csv' })] },
    });

    // Assert
    expect(await screen.findByRole('alert')).toHaveTextContent('Field required');
  });
});