import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Chat from '../Chat';
import { apiService } from '../../services/api';

vi.mock('../../services/api', () => ({
  apiService: {
    sendChatMessage: vi.fn(),
  },
}));

const mockedSendChatMessage = vi.mocked(apiService.sendChatMessage);

describe('Chat sequential parts cancellation', () => {
  beforeEach(() => {
    mockedSendChatMessage.mockReset();
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it('keeps Stop visible and aborts before dispatching later parts', async () => {
    // Arrange
    let partSignal: AbortSignal | undefined;
    mockedSendChatMessage
      .mockResolvedValueOnce({
        action: 'sequential_parts',
        response: 'I will answer this in two parts.',
        session_id: 'session-1',
        parts: [
          { id: 1, query: 'First part', depends_on: [] },
          { id: 2, query: 'Second part', depends_on: [1] },
        ],
      })
      .mockImplementationOnce((...args: any[]) => {
        partSignal = args[12] as AbortSignal;
        return new Promise((_resolve, reject) => {
          partSignal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        });
      });

    const queryClient = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <Chat selectedDataset={null} chatMode geointMode={false} />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Answer two questions' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('I will answer this in two parts.');
    await waitFor(() => expect(mockedSendChatMessage).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText('Working on part 1 of 2…')).toHaveLength(1);
    const stopButton = await screen.findByRole('button', { name: 'Stop generating' });

    // Act
    fireEvent.click(stopButton);

    // Assert
    await waitFor(() => expect(partSignal?.aborted).toBe(true));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument());
    expect(mockedSendChatMessage).toHaveBeenCalledTimes(2);
  });
});
