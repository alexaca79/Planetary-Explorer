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

  it('lists every deployed GPT-5.6 model and its thinking levels', async () => {
    // Arrange
    localStorage.setItem('planetaryexplorer-model', 'gpt-5.6-sol');
    localStorage.setItem('planetaryexplorer-reasoning-effort', 'medium');
    mockedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        checks: {
          azure_openai: {
            status: 'configured',
            model: 'gpt-4o',
            available_models: [
              'gpt-4o',
              'gpt-5.6-sol',
              'gpt-5.6-terra',
              'gpt-5.6-luna',
            ],
            model_capabilities: {
              'gpt-4o': {
                reasoning_efforts: ['none'],
                default_reasoning_effort: 'none',
              },
              'gpt-5.6-sol': {
                reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
                default_reasoning_effort: 'medium',
              },
              'gpt-5.6-terra': {
                reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
                default_reasoning_effort: 'medium',
              },
              'gpt-5.6-luna': {
                reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
                default_reasoning_effort: 'medium',
              },
            },
          },
        },
      }),
    } as Response);
    const onModelChange = vi.fn();
    const onReasoningEffortChange = vi.fn();
    render(
      <ModelSelector
        apiBaseUrl="https://api.example"
        selectedModel="gpt-5.6-sol"
        selectedReasoningEffort="medium"
        onModelChange={onModelChange}
        onReasoningEffortChange={onReasoningEffortChange}
      />
    );

    // Act
    await waitFor(() => expect(onModelChange).toHaveBeenCalledWith('gpt-5.6-sol'));
    fireEvent.click(screen.getByText('Models'));

    // Assert
    expect(screen.getByRole('option', { name: /GPT-5\.6 Sol/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /GPT-5\.6 Terra/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /GPT-5\.6 Luna/i })).toBeInTheDocument();
    for (const label of ['None', 'Low', 'Medium', 'High', 'XHigh', 'Max']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole('button', { name: 'Max' }));
    expect(onReasoningEffortChange).toHaveBeenLastCalledWith('max');
    expect(localStorage.getItem('planetaryexplorer-reasoning-effort')).toBe('max');
  });

  it('falls back to none when switching from GPT-5.6 to GPT-4o', async () => {
    // Arrange
    localStorage.setItem('planetaryexplorer-model', 'gpt-5.6-sol');
    localStorage.setItem('planetaryexplorer-reasoning-effort', 'high');
    mockedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        checks: {
          azure_openai: {
            status: 'configured',
            model: 'gpt-4o',
            available_models: ['gpt-4o', 'gpt-5.6-sol'],
            model_capabilities: {
              'gpt-4o': {
                reasoning_efforts: ['none'],
                default_reasoning_effort: 'none',
              },
              'gpt-5.6-sol': {
                reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
                default_reasoning_effort: 'medium',
              },
            },
          },
        },
      }),
    } as Response);
    const onReasoningEffortChange = vi.fn();
    render(
      <ModelSelector
        apiBaseUrl="https://api.example"
        selectedModel="gpt-5.6-sol"
        selectedReasoningEffort="high"
        onReasoningEffortChange={onReasoningEffortChange}
      />
    );
    await waitFor(() => expect(onReasoningEffortChange).toHaveBeenCalledWith('high'));
    fireEvent.click(screen.getByText('Models'));

    // Act
    fireEvent.click(screen.getByRole('option', { name: /GPT-4o/i }));

    // Assert
    expect(onReasoningEffortChange).toHaveBeenLastCalledWith('none');
    expect(localStorage.getItem('planetaryexplorer-reasoning-effort')).toBe('none');
  });

  it('falls back when a restored model is no longer deployed', async () => {
    // Arrange
    const onModelChange = vi.fn();
    const { rerender } = render(
      <ModelSelector
        apiBaseUrl="https://api.example"
        selectedModel="gpt-4o"
        onModelChange={onModelChange}
      />
    );
    await waitFor(() => expect(onModelChange).toHaveBeenCalledWith('gpt-4o'));
    onModelChange.mockClear();

    // Act
    rerender(
      <ModelSelector
        apiBaseUrl="https://api.example"
        selectedModel="retired-model"
        onModelChange={onModelChange}
      />
    );

    // Assert
    await waitFor(() => expect(onModelChange).toHaveBeenCalledWith('gpt-4o'));
    expect(localStorage.getItem('planetaryexplorer-model')).toBe('gpt-4o');
  });
});