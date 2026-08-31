const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

const escapeHtml = (value: string): string => value.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);

export function renderMessageHTML(content: string): string {
  let rendered = escapeHtml(String(content ?? ''));

  rendered = rendered.replace(/^\s*Preview:\s*.*$/gim, '(shown on map)');
  rendered = rendered.replace(/!\[[^\]]*\]\((https?:[^)]+)\)/g, '(shown on map)');
  rendered = rendered.replace(
    /\[([^\]]+)\]\((https?:[^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  rendered = rendered.replace(
    /(https?:\/\/[\w\-._~:?#\[\]@!$&'()*+,;=%/]+)(?![^<]*>)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  rendered = rendered.replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n');

  const headingStyle = 'font-size:1.05em;font-weight:600;color:#1e3a8a;display:block;margin:14px 0 6px;';
  const listStyle = (marginLeft: number) => `display:block;margin:2px 0 2px ${marginLeft}px;padding-left:14px;text-indent:-14px;line-height:1.45;`;
  const markerStyle = 'display:inline-block;width:14px;color:#475569;font-weight:600;';

  rendered = rendered.replace(
    /^(\d+\))\s+(.+)$/gm,
    `<div style="${headingStyle}">$1 $2</div>`,
  );
  rendered = rendered.replace(/^#{1,4}\s+(.+)$/gm, `<div style="${headingStyle}">$1</div>`);
  rendered = rendered.replace(/^(\s*)(\d+)\.\s+(.+)$/gm, (_match, indent: string, number: string, body: string) => {
    const depth = Math.floor((indent || '').length / 2);
    return `<div style="${listStyle(16 + depth * 18)}"><span style="${markerStyle}">${number}.</span>${body}</div>`;
  });
  rendered = rendered.replace(/^(\s*)[-*•]\s+(.+)$/gm, (_match, indent: string, body: string) => {
    const depth = Math.floor((indent || '').length / 2);
    return `<div style="${listStyle(16 + depth * 18)}"><span style="${markerStyle}">•</span>${body}</div>`;
  });

  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  rendered = rendered.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,;:!?<]|$)/g, '$1<em>$2</em>');
  rendered = rendered.replace(
    /`([^`\n]+)`/g,
    '<code style="background:rgba(148,163,184,0.18);padding:1px 5px;border-radius:3px;font-size:0.92em;">$1</code>',
  );

  rendered = rendered.replace(/\n/g, '<br/>');
  rendered = rendered.replace(/(<\/div>)(<br\/>)+/g, '$1');
  return rendered.replace(/(<br\/>){3,}/g, '<br/><br/>');
}