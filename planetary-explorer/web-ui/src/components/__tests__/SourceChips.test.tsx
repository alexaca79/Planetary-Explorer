import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import SourceChips from '../SourceChips';

describe('SourceChips tool evidence', () => {
  it('shows Web Search and Code Interpreter only when their tool names are returned', () => {
    const { rerender } = render(<SourceChips toolsUsed={['search_web', 'code_interpreter']} />);

    expect(screen.getByText('Tool: Web Search')).toBeInTheDocument();
    expect(screen.getByText('Tool: Code Interpreter')).toBeInTheDocument();

    rerender(<SourceChips toolsUsed={[]} />);

    expect(screen.queryByText('Tool: Code Interpreter')).not.toBeInTheDocument();
  });
});