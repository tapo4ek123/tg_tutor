const { test } = require('node:test');
const assert = require('node:assert/strict');
const { calculateAssessment } = require('./presentation_runtime.js');

test('75% requires practice, 87.5% passes with four criteria',() => {
  assert.equal(calculateAssessment([2,2,1,1],false,false).passed,false);
  const result = calculateAssessment([2,2,2,1],false,false);
  assert.equal(result.score,0.875);
  assert.equal(result.passed,true);
});
test('final work with help requires another independent attempt',() => {
  assert.equal(calculateAssessment([2,2,2,2],true,true).passed,false);
  assert.equal(calculateAssessment([2,2,2,2],true,false).passed,true);
  assert.equal(calculateAssessment([2,2,2,2],false,true).passed,true);
});
test('invalid score input is rejected',() => {
  for (const scores of [[],[3,0],[-1,2],[1.5,2]]) assert.throws(() => calculateAssessment(scores,false,false),RangeError);
});
