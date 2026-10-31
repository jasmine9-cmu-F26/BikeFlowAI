// Offline service mocks exercise the actual Apps Script source; no network.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname,'../deploy/apps_script/Code.gs'),'utf8');

function fixture() {
  const properties = new Map();const files=[];const triggers=[];const logs=[];
  let offline=false, numeric=false, redirect=false, locked=false, serial=0;
  const stamp = Date.parse('2026-10-30T23:00:00Z');
  class Clock extends Date {
    constructor(...args){super(...(args.length?args:[stamp]));}
    static now(){return stamp;}
  }
  const folder = {
    getId(){return 'private-synthetic-folder';},
    getSharingAccess(){return 'PRIVATE';},getEditors(){return [];},getViewers(){return [];},
    getFoldersByName(){return {hasNext(){return true;},next(){return folder;}};},
    createFolder(){return folder;},
    createFile(blob){files.push(blob);return {getId(){return 'file-'+files.length;},getSize(){return blob.bytes.length;}};}
  };
  const props={getProperty(k){return properties.get(k)||null;},setProperty(k,v){properties.set(k,v);return props;}};
  const blob=(data,type,name)=>({bytes:Buffer.from(data),name,type});
  const sandbox={Date:Clock,Set,console:{log(v){logs.push(v);},error(v){logs.push(v);}},
    PropertiesService:{getScriptProperties(){return props;}},
    LockService:{getScriptLock(){return {tryLock(){if(locked)return false;locked=true;return true;},releaseLock(){locked=false;}};}},
    DriveApp:{Access:{PRIVATE:'PRIVATE'},createFolder(){return folder;},getFolderById(){return folder;}},
    ScriptApp:{getProjectTriggers(){return triggers.slice();},deleteTrigger(t){triggers.splice(triggers.indexOf(t),1);},
      newTrigger(handler){return {timeBased(){return this;},everyMinutes(n){assert.equal(n,5);return this;},create(){triggers.push({getHandlerFunction(){return handler;}});}};}},
    Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
      computeDigest(algorithm,text){return [...crypto.createHash('sha256').update(text).digest()];},getUuid(){return 'synthetic-'+(++serial);},
      newBlob:blob,gzip(value,name){return {bytes:zlib.gzipSync(value.bytes),name};}},
    UrlFetchApp:{fetch(url,options){
      assert.equal(options.followRedirects,false);assert.equal(options.validateHttpsCertificates,true);
      if(offline)throw Error('synthetic offline');
      if(redirect)return {getResponseCode(){return 302;},getAllHeaders(){return {Location:'https://untrusted.invalid/status'};}};
      let document;
      if(url.endsWith('gbfs.json'))document={data:{en:{feeds:['station_information','station_status'].map(name=>({name,url:'https://gbfs.lyft.com/'+name+'.json'}))}}};
      else if(url.includes('station_information'))document={data:{stations:[{station_id:'9007199254740993123456789',name:'Synthetic'}]}};
      else document={last_updated:stamp/1000,ttl:60,data:{stations:[{station_id:numeric?123:'9007199254740993123456789',num_bikes_available:2,num_docks_available:8}]}};
      return {getResponseCode(){return 200;},getContentText(){return JSON.stringify(document);}};
    }}
  };
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  return {sandbox,properties,files,triggers,logs,offline(){offline=true;},numeric(){numeric=true;},redirect(){redirect=true;},lock(){locked=true;},
    records(){return files.map(f=>JSON.parse(zlib.gunzipSync(f.bytes).toString('utf8')));}};
}

test('unchanged inventories create two full gzip snapshots preserving exact string IDs',()=>{
  const x=fixture();x.sandbox.setupCollector();x.sandbox.captureDivvySnapshot({triggerUid:'trigger-1'});
  const polls=x.records();assert.equal(polls.length,2);assert.equal(polls[1].invocation,'scheduled');
  for(const r of polls){assert.equal(r.full_snapshot,true);assert.equal(r.unchanged_inventory_suppressed,false);
    const raw=r.sources.station_status.raw_json;
    assert.equal(JSON.parse(raw).data.stations[0].station_id,'9007199254740993123456789');
    assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),r.sources.station_status.sha256_utf8);}
});
test('setup does not schedule; start creates only one 5min trigger and stop preserves files',()=>{
  const x=fixture();x.sandbox.setupCollector();assert.equal(x.triggers.length,0);
  x.sandbox.startCollector();x.sandbox.startCollector();assert.equal(x.triggers.length,1);
  x.triggers.push({getHandlerFunction(){return 'unrelated';}});
  x.sandbox.stopCollector();assert.equal(x.triggers.length,1);assert.equal(x.files.length,1);
});
test('network failures become errors, never empty inventory',()=>{
  const x=fixture();x.sandbox.setupCollector();x.offline();
  assert.throws(()=>x.sandbox.captureDivvySnapshot(),/offline/);
  const r=x.records().at(-1);assert.equal(r.status,'error');assert.equal(r.full_snapshot,false);
});
test('numeric station IDs are rejected instead of silently rounded',()=>{
  const x=fixture();x.sandbox.setupCollector();x.numeric();
  assert.throws(()=>x.sandbox.captureDivvySnapshot(),/non-string/);assert.equal(x.records().at(-1).status,'error');
});
test('untrusted redirect is blocked before a second request',()=>{
  const x=fixture();x.sandbox.setupCollector();x.redirect();
  assert.throws(()=>x.sandbox.captureDivvySnapshot(),/Only official/);
});
test('overlapping invocation cannot create a second poll',()=>{
  const x=fixture();x.sandbox.setupCollector();x.lock();
  assert.equal(x.sandbox.captureDivvySnapshot().status,'overlap_skipped');assert.equal(x.files.length,1);
});
test('runtime guard stops only collector triggers and records an error',()=>{
  const x=fixture();x.sandbox.setupCollector();x.sandbox.startCollector();
  x.properties.set('BIKEFLOW_RUNTIME_BUDGET',JSON.stringify({day:'2026-10-30',ms:65*60*1000}));
  assert.throws(()=>x.sandbox.captureDivvySnapshot(),/daily runtime/);assert.equal(x.triggers.length,0);
  assert.equal(x.records().at(-1).status,'error');
});
