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

interface ModelSelectorProps {
  onModelChange?: (modelId: string) => void;
  selectedModel?: string;
  apiBaseUrl?: string;
}

const displayModelName = (modelId: string) =>
  modelId.replace(/^gpt/i, 'GPT').replace(/-mini$/i, ' Mini');

const ModelSelector: React.FC<ModelSelectorProps> = ({ onModelChange, selectedModel, apiBaseUrl = '' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [currentModel, setCurrentModel] = useState<string>(
    selectedModel || localStorage.getItem('planetaryexplorer-model') || ''
  );
  const dropdownRef = useRef<HTMLDivElement>(null);
  const currentModelRef = useRef(currentModel);
  const onModelChangeRef = useRef(onModelChange);

  useEffect(() => {
    currentModelRef.current = currentModel;
  }, [currentModel]);

  useEffect(() => {
    onModelChangeRef.current = onModelChange;
  }, [onModelChange]);

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

  const handleModelSelect = (modelId: string) => {
    const model = models.find(m => m.id === modelId);
    // Only allow selecting available models
    if (model?.isAvailable) {
      setCurrentModel(modelId);
      setIsOpen(false);
      onModelChange?.(modelId);
    }
  };

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
        </div>
      )}
    </div>
  );
};

export default ModelSelector;
