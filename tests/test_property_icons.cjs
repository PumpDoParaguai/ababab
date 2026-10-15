// Regression test for property CDN icons, independent of Flask/browser networking.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const js = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const begin = js.indexOf('const propEntries =');
const end = js.indexOf('\nfunction listingArt(', begin);
assert.ok(begin >= 0 && end > begin, 'Property rendering section exists');
const context = {
  esc: (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c])),
  imageSafe: (url) => typeof url === 'string' && url.startsWith('https://') ? url : null,
};
vm.createContext(context);
vm.runInContext(js.slice(begin, end) + '\nglobalThis.getBadgeHTML = propHtml; globalThis.getIconURL = propertyIconUrl;', context);
const html = context.getBadgeHTML({properties: {
 glow: {name:'Glow Tail', value:'True', type:'bool'},
 bite: {name:'Bite', value:'True', type:'bool'},
 damage: {name:'Damage', value:'False', type:'bool'},
 group: {name:'Traits', value:'Bite, Damage', type:'string'},
 gender: {name:'Gender', value:'Male', type:'string'},
}});
assert.equal(context.getIconURL('Glowtail'), 'https://cdn.nookazon.com/creaturesofsonaria/properties/Glow_Tail.png');
assert.equal(context.getIconURL('Glow Tail'), 'https://cdn.nookazon.com/creaturesofsonaria/properties/Glow_Tail.png');
assert.equal(context.getIconURL('Bite'), 'https://cdn.nookazon.com/creaturesofsonaria/properties/Bite.png');
assert.equal(context.getIconURL('New Mutation'), 'https://cdn.nookazon.com/creaturesofsonaria/properties/New_Mutation.png');
assert.equal(context.getIconURL('!!!'), null);
assert.ok(html.includes('Glow_Tail.png'), 'Glowtail icon shown');
assert.ok(html.includes('Bite.png'), 'Bite icon shown');
assert.ok(html.includes('Damage.png'), 'Grouped trait icon shown');
assert.ok(html.includes('Gender:'), 'Non-icon property preserved');
assert.ok(!/Glow Tail:\s*True|Bite:\s*True|Damage:\s*False/.test(html), 'Raw boolean values suppressed');
const separate = context.getBadgeHTML({properties:{mutation:{name:'Mutation',value:'Glow Tail',type:'string'}}});
assert.ok(separate.includes('Glow_Tail.png'), 'Single mutation value has icon');
console.log('Passed: property icons, grouped traits, bools, safe URL generation.');

const supplied=context.getBadgeHTML({properties:{c:{name:'Corrupt',type:'bool',value:'True',icon_url:'https://cdn.example.com/corrupt-real.webp'},slot:{name:'Species or Slot?',type:'string',value:'Slot'}}});
assert.ok(supplied.includes('src="https://cdn.example.com/corrupt-real.webp"'), 'API image takes precedence over guessed filenames');
assert.ok(supplied.includes('/static/icons/corrupt.svg'), 'Corrupt has a bundled fallback');
assert.ok(supplied.includes('>Slot</span>') && !supplied.includes('Species or Slot'), 'Only the slot label is visible');
const species=context.getBadgeHTML({properties:{mode:{name:'Species or Slot?',type:'string',value:'Species'}}});
assert.ok(species.includes('>Espécie</span>'));
