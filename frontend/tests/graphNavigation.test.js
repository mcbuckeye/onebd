import assert from 'node:assert/strict';
import test from 'node:test';
import { graphNodePath } from '../src/lib/graphNavigation.js';

test('routes a prefixed company graph node to its numeric company profile', () => {
  assert.equal(
    graphNodePath({ id: 'company_1379851', type: 'company' }),
    '/company/1379851',
  );
});

test('routes a prefixed deal graph node to its deal page', () => {
  assert.equal(graphNodePath({ id: 'deal_42', type: 'deal' }), '/deals/42');
});

test('supports legacy numeric company node IDs', () => {
  assert.equal(graphNodePath({ id: '1379851' }), '/company/1379851');
});

test('does not navigate unknown graph entity IDs', () => {
  assert.equal(graphNodePath({ id: 'company_not-a-number', type: 'company' }), null);
});
