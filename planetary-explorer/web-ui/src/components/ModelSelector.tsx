// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

import React, { useState, useEffect, useRef } from 'react';
import './ModelSelector.css';
import { authenticatedFetch } from '../services/authHelper';

interface ModelOption {
  id: string;
  name: string;
  isDefault?: boolean;
  isAvailable?: boolean;
}

interface ModelCapability {
  reasoning_efforts: string[];
  default_reasoning_effort: string;
}

interface ModelSelectorProps {
  onModelChange?: (modelId: string) => void;
  onReasoningEffortChange?: (effort: string) => void;
  selectedModel?: string;
  selectedReasoningEffort?: string;
  apiBaseUrl?: string;
}

const displayModelName = (modelId: string) =>
  modelId
    .replace(/^gpt/i, 'GPT')
    .replace(/-(mini|sol|terra|luna)$/i, (_, suffix: string) =>
      ` ${suffix.charAt(0).toUpperCase()}${suffix.slice(1)}`
    );

const displayEffortName = (effort: string) =>
  effort === 'xhigh'
    ? 'XHigh'
    : `${effort.charAt(0).toUpperCase()}${effort.slice(1)}`;

const DEFAULT_CAPABILITY: ModelCapability = {
  reasoning_efforts: ['none'],
  default_reasoning_effort: 'none',
};

const ModelSelector: React.FC<ModelSelectorProps> = ({
  onModelChange,
  onReasoningEffortChange,
  selectedModel,
  selectedReasoningEffort,
  apiBaseUrl = '',
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [capabilities, setCapabilities] = useState<Record<string, ModelCapability>>({});
  const [currentModel, setCurrentModel] = useState<string>(
    selectedModel || localStorage.getItem('planetaryexplorer-model') || ''
  );
  const [currentReasoningEffort, setCurrentReasoningEffort] = useState<string>(
    selectedReasoningEffort
      || localStorage.getItem('planetaryexplorer-reasoning-effort')
      || 'none'
  );
  const dropdownRef = useRef<HTMLDivElement>(null);
  const currentModelRef = useRef(currentModel);
  const currentReasoningEffortRef = useRef(currentReasoningEffort);
  const onModelChangeRef = useRef(onModelChange);
  const onReasoningEffortChangeRef = useRef(onReasoningEffortChange);

  useEffect(() => {
    currentModelRef.current = currentModel;
  }, [currentModel]);

  useEffect(() => {
    currentReasoningEffortRef.current = currentReasoningEffort;
  }, [currentReasoningEffort]);

  useEffect(() => {
    onModelChangeRef.current = onModelChange;
  }, [onModelChange]);

  useEffect(() => {
    onReasoningEffortChangeRef.current = onReasoningEffortChange;
  }, [onReasoningEffortChange]);

  useEffect(() => {
    if (models.length === 0 || !selectedModel) return;
    const fallbackModel = models.find((model) => model.isDefault)?.id || models[0].id;
    const nextModel = models.some(
      (model) => model.id === selectedModel && model.isAvailable,
    )
      ? selectedModel
      : fallbackModel;
    const capability = capabilities[nextModel] || DEFAULT_CAPABILITY;
    const requestedEffort = selectedReasoningEffort || currentReasoningEffortRef.current;
    const nextEffort = capability.reasoning_efforts.includes(requestedEffort)
      ? requestedEffort
      : capability.default_reasoning_effort;

    setCurrentModel(nextModel);
    setCurrentReasoningEffort(nextEffort);
    localStorage.setItem('planetaryexplorer-model', nextModel);
    localStorage.setItem('planetaryexplorer-reasoning-effort', nextEffort);
    if (nextModel !== selectedModel) onModelChangeRef.current?.(nextModel);
    if (nextEffort !== selectedReasoningEffort) {
      onReasoningEffortChangeRef.current?.(nextEffort);
    }
  }, [capabilities, models, selectedModel, selectedReasoningEffort]);

  // Fetch available models from health endpoint
  useEffect(() => {
    const fetchAvailableModels = async () => {
      try {
        const response = await authenticatedFetch(`${apiBaseUrl}/api/health`);
        const data = await response.json();
        const openai = data.checks?.azure_openai || data.connectivity_tests?.azure_openai;
        const openaiStatus = openai?.status;
        const isOpenAiOk = ['connected', 'configured', 'healthy', 'ok'].includes(openaiStatus?.toLowerCase() || '');

        if (isOpenAiOk && openai?.model) {
          const availableModels = Array.from(new Set(
            (openai.available_models || [openai.model]).filter(Boolean)
          )) as string[];
          const modelCapabilities = (openai.model_capabilities || {}) as Record<string, ModelCapability>;
          setCapabilities(modelCapabilities);
          setModels(availableModels.map(modelId => ({
            id: modelId,
            name: displayModelName(modelId),
            isDefault: modelId === openai.model,
            isAvailable: true,
          })));

          const nextModel = availableModels.includes(currentModelRef.current)
            ? currentModelRef.current
            : openai.model;
          setCurrentModel(nextModel);
          localStorage.setItem('planetaryexplorer-model', nextModel);
          onModelChangeRef.current?.(nextModel);

          const capability = modelCapabilities[nextModel] || DEFAULT_CAPABILITY;
          const nextEffort = capability.reasoning_efforts.includes(currentReasoningEffortRef.current)
            ? currentReasoningEffortRef.current
            : capability.default_reasoning_effort;
          setCurrentReasoningEffort(nextEffort);
          localStorage.setItem('planetaryexplorer-reasoning-effort', nextEffort);
          onReasoningEffortChangeRef.current?.(nextEffort);
        }
      } catch (err) {
        console.error('Failed to fetch model availability:', err);
      }
    };

    fetchAvailableModels();
    // Refresh every 30 seconds
    const interval = setInterval(fetchAvailableModels, 30000);
    return () => clearInterval(interval);
  }, [apiBaseUrl]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Store model preference in localStorage
  useEffect(() => {
    localStorage.setItem('planetaryexplorer-model', currentModel);
  }, [currentModel]);

  useEffect(() => {
    localStorage.setItem('planetaryexplorer-reasoning-effort', currentReasoningEffort);
  }, [currentReasoningEffort]);

  const handleModelSelect = (modelId: string) => {
    const model = models.find(m => m.id === modelId);
    // Only allow selecting available models
    if (model?.isAvailable) {
      setCurrentModel(modelId);
      const capability = capabilities[modelId] || DEFAULT_CAPABILITY;
      const nextEffort = capability.reasoning_efforts.includes(currentReasoningEffort)
        ? currentReasoningEffort
        : capability.default_reasoning_effort;
      setCurrentReasoningEffort(nextEffort);
      setIsOpen(false);
      onModelChange?.(modelId);
      onReasoningEffortChange?.(nextEffort);
    }
  };

  const handleReasoningEffortSelect = (effort: string) => {
    const capability = capabilities[currentModel] || DEFAULT_CAPABILITY;
    if (!capability.reasoning_efforts.includes(effort)) return;
    setCurrentReasoningEffort(effort);
    onReasoningEffortChange?.(effort);
  };

  const currentCapability = capabilities[currentModel] || DEFAULT_CAPABILITY;

  return (
    <div className="model-selector" ref={dropdownRef}>
      <div 
        className="model-selector-button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        title="Deployed model status"
      >
        <span className="model-selector-label">Models</span>
      </div>
      
      {isOpen && (
        <div className="model-dropdown">
          <ul className="model-list" role="listbox">
            {models.length === 0 && (
              <li className="model-option unavailable" aria-disabled="true">
                <span className="model-option-name">Checking deployment</span>
              </li>
            )}
            {models.map((model) => (
              <li
                key={model.id}
                className={`model-option ${currentModel === model.id ? 'selected' : ''} ${!model.isAvailable ? 'unavailable' : ''}`}
                onClick={() => handleModelSelect(model.id)}
                role="option"
                aria-selected={currentModel === model.id}
                aria-disabled={!model.isAvailable}
                style={{ opacity: model.isAvailable ? 1 : 0.5 }}
              >
                <span className="model-option-name">{model.name}</span>
                <span 
                  className="model-availability-dot"
                  style={{ 
                    backgroundColor: model.isAvailable ? '#4CAF50' : '#F44336',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    marginLeft: '8px',
                    display: 'inline-block'
                  }}
                  title={model.isAvailable ? 'Available' : 'Not Deployed'}
                />
                {currentModel === model.id && <span className="check-mark">✓</span>}
              </li>
            ))}
          </ul>
          <div className="reasoning-section">
            <div className="reasoning-section-title">Thinking level</div>
            <div className="reasoning-options" role="group" aria-label="Thinking level">
              {currentCapability.reasoning_efforts.map((effort) => (
                <button
                  key={effort}
                  type="button"
                  className={`reasoning-option ${currentReasoningEffort === effort ? 'selected' : ''}`}
                  aria-pressed={currentReasoningEffort === effort}
                  onClick={() => handleReasoningEffortSelect(effort)}
                >
                  {displayEffortName(effort)}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ModelSelector;
