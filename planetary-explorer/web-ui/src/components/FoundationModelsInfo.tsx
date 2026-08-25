// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

import React, { useEffect, useRef, useState } from 'react';
import { authenticatedFetch } from '../services/authHelper';
import './FoundationModelsInfo.css';

export interface FoundationModelStatus {
  profile: string;
  model_id: string;
  model_revision: string;
  approval_state: string;
  supported_collections: string[];
  geographic_scope: string;
  license: string;
}

export interface FoundationModelsHealth {
  status: string;
  enabled: boolean;
  connected: boolean;
  endpoint_host: string;
  tool_count: number;
  tools: string[];
  models: FoundationModelStatus[];
}

interface FoundationModelsInfoProps {
  apiBaseUrl?: string;
}

const EMPTY_HEALTH: FoundationModelsHealth = {
  status: 'loading',
  enabled: false,
  connected: false,
  endpoint_host: '',
  tool_count: 0,
  tools: [],
  models: [],
};

const formatTool = (tool: string): string => {
  const names: Record<string, string> = {
    geofm_list_models: 'Model registry',
    geofm_compare_epochs: 'Epoch comparison',
    geofm_get_run: 'Run monitoring',
    geofm_cancel_run: 'Run cancellation',
  };
  return names[tool] || tool.replace(/^geofm_/, '').split('_').join(' ');
};

const shortRevision = (revision: string): string => revision ? revision.slice(0, 12) : 'Not reported';

const FoundationModelsInfo: React.FC<FoundationModelsInfoProps> = ({ apiBaseUrl = '' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [health, setHealth] = useState<FoundationModelsHealth>(EMPTY_HEALTH);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const response = await authenticatedFetch(`${apiBaseUrl}/api/health`);
        const payload = await response.json();
        const snapshot = payload.checks?.geospatial_foundation_models;
        if (!snapshot) throw new Error('Health payload omitted foundation model status');
        if (!cancelled) {
          setHealth(snapshot);
          setError(response.ok ? null : `Health endpoint returned ${response.status}`);
        }
      } catch (reason) {
        console.error('Foundation model status failed:', reason);
        if (!cancelled) {
          setHealth({ ...EMPTY_HEALTH, status: 'unavailable' });
          setError('Foundation model status is unavailable.');
        }
      }
    };

    refresh();
    const interval = window.setInterval(refresh, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [apiBaseUrl]);

  useEffect(() => {
    if (!isOpen) return undefined;
    closeButtonRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
      if (event.key !== 'Tab' || !dialogRef.current) return;

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>('button, [href], [tabindex]:not([tabindex="-1"])')
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      triggerRef.current?.focus();
    };
  }, [isOpen]);

  const connected = health.enabled && health.connected;
  const statusLabel = connected ? 'MCP connected' : health.enabled ? 'MCP unavailable' : 'Not enabled';

  return (
    <div className="foundation-models-info">
      <button
        type="button"
        className="foundation-models-tab"
        ref={triggerRef}
        onClick={() => setIsOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        title="Geospatial foundation models"
      >
        <span className={`foundation-models-dot ${connected ? 'connected' : ''}`} aria-hidden="true" />
        <span>Foundation Models</span>
      </button>

      {isOpen && (
        <div className="foundation-models-overlay" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setIsOpen(false);
        }}>
          <div className="foundation-models-panel" role="dialog" aria-modal="true" aria-labelledby="foundation-models-title" aria-describedby="foundation-models-description" ref={dialogRef}>
            <header className="foundation-models-header">
              <div>
                <div className="foundation-models-kicker">Analysis runtime</div>
                <h2 id="foundation-models-title">Geospatial Foundation Models</h2>
                <p id="foundation-models-description">Registered models and connected analysis capabilities.</p>
              </div>
              <button type="button" className="foundation-models-close" ref={closeButtonRef} onClick={() => setIsOpen(false)} aria-label="Close foundation models">×</button>
            </header>

            <div className="foundation-models-connection">
              <span className={`foundation-models-state ${connected ? 'connected' : ''}`}>{statusLabel}</span>
              <span>{health.endpoint_host || 'No MCP endpoint configured'}</span>
              <span>{health.tool_count} analysis tools</span>
            </div>

            <div className="foundation-models-body">
              {error && <div className="foundation-models-empty">{error}</div>}
              {!error && health.models.length === 0 && (
                <div className="foundation-models-empty">No geospatial foundation models are currently advertised.</div>
              )}
              {health.models.map((model) => (
                <section className="foundation-model-row" key={`${model.model_id}-${model.model_revision}`}>
                  <div className="foundation-model-identity">
                    <div className="foundation-model-name">{model.model_id}</div>
                    <div className="foundation-model-profile">{model.profile.split('_').join(' ')}</div>
                  </div>
                  <dl className="foundation-model-facts">
                    <div><dt>Revision</dt><dd title={model.model_revision}>{shortRevision(model.model_revision)}</dd></div>
                    <div><dt>Deployment gate</dt><dd>{model.approval_state || 'Not reported'}</dd></div>
                    <div><dt>Geographic scope</dt><dd>{model.geographic_scope || 'Not reported'}</dd></div>
                    <div><dt>Collections</dt><dd>{model.supported_collections.join(', ') || 'Not reported'}</dd></div>
                  </dl>
                </section>
              ))}

              {health.tools.length > 0 && (
                <section className="foundation-model-tools">
                  <h3>Connected analysis capabilities</h3>
                  <div className="foundation-model-tool-list">
                    {health.tools.map((tool) => <span key={tool}>{formatTool(tool)}</span>)}
                  </div>
                </section>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default FoundationModelsInfo;