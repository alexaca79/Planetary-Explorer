// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

import React, { useEffect, useRef, useState } from 'react';
import { authenticatedFetch } from '../services/authHelper';
import { isHexColour } from '../utils/geofmOverlay';
import './FoundationModelsInfo.css';

export interface FoundationModelStatus {
  profile: string;
  model_id: string;
  model_revision: string;
  approval_state: string;
  supported_collections: string[];
  geographic_scope: string;
  license: string;
  capability?: string;
  sensor_family?: string;
  classification_mode?: string;
  class_scheme_id?: string;
  mandatory_warnings?: string[];
}

export interface FoundationClassLabel {
  class_value: number;
  name: string;
  colour_hex: string;
  description: string;
}

export interface FoundationClassScheme {
  scheme_id: string;
  version: string;
  source: string;
  license: string;
  labels: FoundationClassLabel[];
}

export interface FoundationModelsHealth {
  status: string;
  enabled: boolean;
  connected: boolean;
  endpoint_host: string;
  tool_count: number;
  tools: string[];
  models: FoundationModelStatus[];
  class_schemes?: FoundationClassScheme[];
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
  class_schemes: [],
};

const formatTool = (tool: string): string => {
  const names: Record<string, string> = {
    geofm_list_models: 'Model registry',
    geofm_compare_epochs: 'Epoch comparison',
    geofm_get_run: 'Run monitoring',
    geofm_retry_run: 'Run retry',
    geofm_cancel_run: 'Run cancellation',
    geofm_classify_aoi: 'Land cover classification',
    geofm_list_class_schemes: 'Class scheme registry',
  };
  return names[tool] || tool.replace(/^geofm_/, '').split('_').join(' ');
};

const shortRevision = (revision: string): string => revision ? revision.slice(0, 12) : 'Not reported';

const CAPABILITY_LABELS: Record<string, string> = {
  change_detection: 'Contextual change',
  classify: 'Land cover classification',
};

const SENSOR_LABELS: Record<string, string> = {
  optical: 'Optical',
  sar: 'SAR (radar)',
  coarse_optical: 'Coarse optical',
};

/** A profile is only usable when its deployment gate is not blocked. */
const isAvailable = (model: FoundationModelStatus): boolean =>
  (model.approval_state || '').toLowerCase() !== 'blocked';

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
          setError(
            snapshot.enabled && !snapshot.connected
              ? 'Foundation model status is unavailable.'
              : null
          );
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
                    <div><dt>Capability</dt><dd>{CAPABILITY_LABELS[model.capability || ''] || model.capability || 'Not reported'}</dd></div>
                    <div><dt>Sensor</dt><dd>{SENSOR_LABELS[model.sensor_family || ''] || model.sensor_family || 'Not reported'}</dd></div>
                    <div><dt>Deployment gate</dt><dd>{model.approval_state || 'Not reported'}</dd></div>
                    <div><dt>Geographic scope</dt><dd>{model.geographic_scope || 'Not reported'}</dd></div>
                    <div><dt>Collections</dt><dd>{model.supported_collections.join(', ') || 'Not reported'}</dd></div>
                    <div><dt>Licence</dt><dd>{model.license || 'Not reported'}</dd></div>
                    {model.class_scheme_id && (
                      <div><dt>Class scheme</dt><dd>{model.class_scheme_id}{model.classification_mode ? ` (${model.classification_mode})` : ''}</dd></div>
                    )}
                  </dl>
                  {!isAvailable(model) && (
                    <p className="foundation-model-blocked">
                      Not yet available in this deployment — this profile stays blocked
                      until its validation report passes.
                    </p>
                  )}
                  {(model.mandatory_warnings || []).length > 0 && (
                    <ul className="foundation-model-warnings">
                      {(model.mandatory_warnings || []).map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}

              {(health.class_schemes || []).length > 0 && (
                <section className="foundation-model-schemes">
                  <h3>Published class schemes</h3>
                  {(health.class_schemes || []).map((scheme) => (
                    <div className="foundation-model-scheme" key={scheme.scheme_id}>
                      <div className="foundation-model-scheme-name">
                        {scheme.scheme_id}{scheme.version ? ` v${scheme.version}` : ''}
                      </div>
                      <div className="foundation-model-scheme-meta">
                        {scheme.source || 'Source not reported'} · {scheme.license || 'Licence not reported'}
                      </div>
                      <div className="foundation-model-scheme-labels">
                        {scheme.labels.map((label) => (
                          <span key={`${scheme.scheme_id}-${label.class_value}`} title={label.description}>
                            <span
                              className="foundation-model-swatch"
                              style={{
                                backgroundColor: isHexColour(label.colour_hex)
                                  ? label.colour_hex
                                  : 'transparent',
                              }}
                              aria-hidden="true"
                            />
                            {label.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </section>
              )}

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