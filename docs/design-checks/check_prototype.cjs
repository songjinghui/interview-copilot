// Isolated source-level interaction checks, NOT browser rendering or accessibility tests.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../prototypes/workbench.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const handlers = {}, nodes = new Map();
function node(s) {
  if (!nodes.has(s)) nodes.set(s, { innerHTML:'', textContent:'', classList:{add(){},remove(){}}, showModal(){this.open=true}, close(){this.open=false} });
  return nodes.get(s);
}
const location = { _hash:'#jobs', get hash(){return this._hash}, set hash(v){this._hash=v.startsWith('#')?v:'#'+v} };
const context = vm.createContext({
  document:{querySelector:node,querySelectorAll:()=>[],addEventListener:(k,f)=>handlers[k]=f},
  window:{addEventListener(){}},location,setTimeout:()=>1,clearTimeout(){},
  FormData:class {constructor(form){this.entries=Object.entries(form.values)}[Symbol.iterator](){return this.entries[Symbol.iterator]()}get(k){return this.entries.find(x=>x[0]===k)?.[1]}}
});
vm.runInContext(script, context);
const snapshot = ()=>JSON.parse(vm.runInContext('JSON.stringify(state)',context));
const click = act=>handlers.click({target:{closest:()=>({dataset:{act}})}});
const change = (id,value,checked)=>handlers.change({target:{id,value,checked}});
const view = ()=>node('#view').innerHTML;
let checks=0;
function check(name, body){body();console.log('PASS '+name);checks++}

check('all prototype routes produce labeled content',()=>{
  for(const route of ['home','jobs','opportunities','prepare','record','interviews','interview','report','improvements','profile','settings','tasks']){
    vm.runInContext(`nav('${route}')`,context);assert.match(view(),/<h1>/);assert.doesNotMatch(view(),/undefined/);
  }
});
check('present has exactly two preparation confirmations, no application',()=>{
  click('reset');vm.runInContext("nav('prepare')",context);click('confirm-materials');assert.equal(snapshot().step,1);assert.match(view(),/知道了，继续去投递/);click('confirm-cooldown');assert.equal(snapshot().step,2);click('open-apply');assert.equal(snapshot().application,null);
});
check('absent and unknown require one confirmation',()=>{
  for(const mode of ['absent','unknown']){change('cooldown',mode);click('confirm-materials');assert.equal(snapshot().step,2);assert.doesNotMatch(view(),/data-act="confirm-cooldown"/)}
});
check('resume exception required and edit clears confirmations',()=>{
  change('prepResume','none');click('confirm-materials');assert.equal(snapshot().step,0);assert.match(node('#prepError').textContent,/说明/);change('exception','此渠道只填在线资料');click('confirm-materials');assert.equal(snapshot().step,2);change('exception','修订说明');assert.equal(snapshot().step,0);
});
check('direct interview entry creates no application',()=>{
  click('reset');handlers.submit({preventDefault(){},target:{id:'interviewForm',values:{title:'已有面试',company:'虚构企业',label:'第二轮',date:''}}});assert.equal(snapshot().interview.title,'已有面试');assert.equal(snapshot().application,null);assert.match(view(),/本场复盘的四项材料/);
});
check('each combined segment resolves its own audio label',()=>{
  click('play-a');assert.match(node('#toast').textContent,/录音 A/);click('play-b');assert.match(node('#toast').textContent,/录音 B/);
});
check('paused task remains paused after simulated restart',()=>{
  click('pause');click('restart');assert.equal(snapshot().task,'paused');click('resume');assert.equal(snapshot().task,'queued');click('finish');assert.equal(snapshot().task,'succeeded');let generation=snapshot().generation;click('rerun');assert.equal(snapshot().generation,generation+1);
});
check('regenerating a report preserves independent improvement progress',()=>{
  click('review');click('add-improvement');change('done',null,true);click('regenerate');assert.equal(snapshot().done,true);assert.equal(snapshot().added,true);
});
check('missing interview content disables review in the generated page',()=>{
  vm.runInContext("nav('interview')",context);change('reviewText','missing');assert.match(view(),/data-act="review" disabled/);
});
check('published report retains its selected input snapshot',()=>{
  change('reviewText','combined');change('reviewJd','v2');click('review');change('reviewJd','missing');vm.runInContext("nav('report')",context);assert.equal(snapshot().reportInputs?.jd,'v2','published report must retain its input snapshot');
});
console.log(`${checks} source-level checks passed; browser pixels, focus and real services remain unverified.`);
