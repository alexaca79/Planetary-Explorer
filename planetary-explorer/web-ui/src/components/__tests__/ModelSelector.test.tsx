import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ModelSelector from '../ModelSelector';
import { authenticatedFetch } from '../../services/authHelper';

vi.mock('../../services/authHelper', () => ({
  authenticatedFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(authenticatedFetch);

describe('ModelSelector', () => {
  beforeEach(() => {
    localStorage.setItem('planetaryexplorer-model', 'gpt-5');
    mockedFetch.mockReset();
    mockedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        checks: {
          azure_openai: {
            status: 'configured',
            model: 'gpt-4o',
            available_models: ['gpt-4o'],
          },
        },
      }),
    } as Response);
  });

  it('replaces a stale saved model with the deployed model', async () => {
    // Arrange
    const onModelChange = vi.fn();
    render(
      <ModelSelector
        apiBaseUrl="https://api.example"
        selectedModel="gpt-5"
        onModelChange={onModelChange}
      />
    );

    // Act
    await waitFor(() => expect(onModelChange).toHaveBeenCalledWith('gpt-4o'));
    fireEvent.click(screen.getByText('Models'));

    // Assert
    expect(screen.getByRole('option', { name: /GPT-4o/i })).toBeInTheDocument();
    expect(screen.queryByText('GPT-5')).not.toBeInTheDocument();
    expect(localStorage.getItem('planetaryexplorer-model')).toBe('gpt-4o');
  });
});