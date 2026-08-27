import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DataLegend from '../DataLegend';
import type { GeoFmClassLegend } from '../../utils/geofmOverlay';

const CLASS_LEGEND: GeoFmClassLegend = {
  schemeId: 'planaura_unsupervised_v1',
  entries: [
    {
      value: 1,
      name: 'Water-like',
      colour: '#2b6cb0',
      areaKm2: 4.25,
      percentOfClassified: 31.5,
      meanConfidence: 0.82,
    },
    {
      value: 2,
      name: 'Vegetation-like',
      colour: '#276749',
      areaKm2: 9.25,
      percentOfClassified: 68.5,
      meanConfidence: null,
    },
  ],
};

describe('DataLegend class legend', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('renders every class with its share and confidence', () => {
    // Arrange & Act
    render(<DataLegend collection="" isVisible={false} classLegend={CLASS_LEGEND} />);

    // Assert
    const legend = screen.getByTestId('geofm-class-legend');
    expect(legend).toHaveTextContent('Water-like');
    expect(legend).toHaveTextContent('31.5% · conf 0.82');
    expect(legend).toHaveTextContent('Vegetation-like');
    expect(legend).toHaveTextContent('68.5%');
  });

  it('always names the class scheme and states the results are unsupervised', () => {
    // Arrange & Act
    render(<DataLegend collection="" isVisible={false} classLegend={CLASS_LEGEND} />);

    // Assert
    const legend = screen.getByTestId('geofm-class-legend');
    expect(legend).toHaveTextContent('Scheme planaura_unsupervised_v1');
    expect(legend).toHaveTextContent('Unsupervised clusters');
    expect(legend).toHaveTextContent('not a validated land-cover product');
  });

  it('does not fetch a continuous colormap when a class legend is shown', () => {
    // Arrange & Act
    render(<DataLegend collection="" isVisible={false} classLegend={CLASS_LEGEND} />);

    // Assert
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders nothing when hidden and no class legend is supplied', () => {
    // Arrange & Act
    const { container } = render(
      <DataLegend collection="cop-dem-glo-30" isVisible={false} classLegend={null} />
    );

    // Assert
    expect(container).toBeEmptyDOMElement();
  });

  it('ignores an empty class legend so a run with no classes renders nothing', () => {
    // Arrange & Act
    const { container } = render(
      <DataLegend
        collection=""
        isVisible={false}
        classLegend={{ schemeId: 'planaura_unsupervised_v1', entries: [] }}
      />
    );

    // Assert
    expect(container).toBeEmptyDOMElement();
  });
});
