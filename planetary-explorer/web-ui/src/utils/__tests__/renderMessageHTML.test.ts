import { describe, expect, it } from 'vitest';

import { renderMessageHTML } from '../renderMessageHTML';

describe('renderMessageHTML', () => {
  it('escapes raw HTML before rendering controlled markup', () => {
    const html = renderMessageHTML('<script>alert("x")</script><img src=x onerror=alert(1)>');
    const container = document.createElement('div');
    container.innerHTML = html;

    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<script>alert("x")</script>');
  });

  it('does not turn non-http markdown targets into links', () => {
    const html = renderMessageHTML('[click](javascript:alert(1))');
    const container = document.createElement('div');
    container.innerHTML = html;

    expect(container.querySelector('a')).toBeNull();
  });

  it('preserves supported markdown and safe links', () => {
    const html = renderMessageHTML('## Results\n- **Toronto** and _Halifax_\n`2026` [Docs](https://example.com/docs)');
    const container = document.createElement('div');
    container.innerHTML = html;

    expect(container.querySelector('strong')?.textContent).toBe('Toronto');
    expect(container.querySelector('em')?.textContent).toBe('Halifax');
    expect(container.querySelector('code')?.textContent).toBe('2026');
    expect(container.querySelector('a')?.getAttribute('href')).toBe('https://example.com/docs');
    expect(container.querySelector('a')?.getAttribute('rel')).toBe('noopener noreferrer');
  });
});