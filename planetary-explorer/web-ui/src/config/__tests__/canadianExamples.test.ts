import { describe, expect, it } from 'vitest';

import {
  buildingDamageQueries,
  exampleQueries,
  extremeWeatherQueries,
  forecastQueries,
  mobilityQueries,
  resilienceQueries,
  siteAuditQueries,
  terrainQueries,
} from '../canadianExamples';

const canadianPlace = /Canada|Alberta|British Columbia|Manitoba|Nova Scotia|Ontario|Quebec|Saskatchewan|Yukon/i;
const legacyPlace = /Afghanistan|Arizona|Australia|Bangladesh|California|Colorado|Ecuador|Florida|Louisiana|Mexico|Mozambique|Nepal|Sudan|Texas|Thailand|Ukraine|United Kingdom|Virginia|Washington, DC/i;

const workflowExamples = [
  ...terrainQueries.map((example) => ({ context: `${example.location} ${example.setupQuery}`, prompt: example.question })),
  ...mobilityQueries.map((example) => ({ context: `${example.location} ${example.setupQuery}`, prompt: example.question })),
  ...siteAuditQueries.map((example) => ({ context: `${example.location} ${example.setupQuery}`, prompt: example.question })),
  ...resilienceQueries.map((example) => ({ context: `${example.scenario} ${example.setupQuery}`, prompt: example.question })),
  ...forecastQueries.map((example) => ({ context: `${example.scenario} ${example.setupQuery}`, prompt: example.question })),
  ...extremeWeatherQueries.map((example) => ({ context: `${example.location} ${example.setupQuery}`, prompt: example.question })),
  ...buildingDamageQueries.map((example) => ({ context: `${example.location} ${example.setupQuery}`, prompt: example.question })),
  ...exampleQueries.flatMap((category) => category.examples.map((example) => ({ context: example.query, prompt: example.query }))),
];

describe('Canadian starter examples', () => {
  it('keeps every primary workflow prompt in 2026', () => {
    expect(workflowExamples.every(({ prompt }) => prompt.includes('2026'))).toBe(true);
  });

  it('keeps every workflow example in a Canadian context', () => {
    expect(workflowExamples.every(({ context }) => canadianPlace.test(context))).toBe(true);
  });

  it('does not reintroduce legacy international example locations', () => {
    const allText = workflowExamples.map(({ context, prompt }) => `${context} ${prompt}`).join('\n');

    expect(allText).not.toMatch(legacyPlace);
  });
});