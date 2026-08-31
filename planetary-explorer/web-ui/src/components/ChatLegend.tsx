import React from 'react';
import { Palette } from 'lucide-react';

import type { ChatLegendDefinition } from '../services/api';
import './ChatLegend.css';

interface ChatLegendProps {
  legend: ChatLegendDefinition;
}

const ChatLegend: React.FC<ChatLegendProps> = ({ legend }) => (
  <section className="chat-legend" aria-label={`${legend.title} colour legend`}>
    <div className="chat-legend__title">
      <Palette size={14} aria-hidden="true" />
      <span>{legend.title}</span>
    </div>
    {legend.gradient && (
      <div className="chat-legend__continuous">
        <div className="chat-legend__gradient" style={{ background: legend.gradient }} />
        <div className="chat-legend__range">
          <span>{legend.minLabel}</span>
          <span>{legend.maxLabel}</span>
        </div>
      </div>
    )}
    {legend.items.length > 0 && (
      <div className="chat-legend__items">
        {legend.items.map((item) => (
          <div className="chat-legend__item" key={`${item.color}-${item.label}`}>
            <span className="chat-legend__swatch" style={{ backgroundColor: item.color }} aria-hidden="true" />
            <span className="chat-legend__label">{item.label}</span>
            {item.description && <span className="chat-legend__description">{item.description}</span>}
          </div>
        ))}
      </div>
    )}
    {legend.note && <p className="chat-legend__note">{legend.note}</p>}
  </section>
);

export default ChatLegend;