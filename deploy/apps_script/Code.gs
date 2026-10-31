/** BikeFlow AI: private full Divvy polls on Google Apps Script free quotas.
 * No billing API, public endpoint, paid subscription or raw-data Git commit.
 * Five-minute triggers are best-effort; actual source/request/receipt times win.
 */
const BIKEFLOW = Object.freeze({
  version: 'apps-script-v2-health',
  discovery: 'https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json',
  hosts: ['gbfs.divvybikes.com', 'gbfs.lyft.com'],
  intervalMinutes: 5,
  stopAtUtc: '2026-12-13T07:59:00Z',
  folderProperty: 'BIKEFLOW_CAPTURE_FOLDER_ID',
  handler: 'captureDivvySnapshot',
  runtimeBudgetMs: 65 * 60 * 1000
});

function sha256_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8)
    .map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}

function officialUrl_(url) {
  const match = /^https:\/\/([^/?#]+)(\/[^#]*)?$/i.exec(url);
  if (!match || BIKEFLOW.hosts.indexOf(match[1].toLowerCase()) < 0) {
    throw new Error('Only official Divvy/Lyft HTTPS hosts are allowed');
  }
  return url;
}

function fetchOfficial_(url) {
  for (let redirects = 0; redirects <= 3; redirects++) {
    officialUrl_(url);
    const requested = new Date().toISOString();
    const response = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true, followRedirects: false, validateHttpsCertificates: true
    });
    const received = new Date().toISOString();
    const code = response.getResponseCode();
    if (code >= 300 && code < 400) {
      const headers = response.getAllHeaders();
      const key = Object.keys(headers).find(function (k) { return k.toLowerCase() === 'location'; });
      if (!key || redirects === 3) throw new Error('Invalid or excessive official redirect');
      let next = String(headers[key]);
      if (next.charAt(0) === '/') next = /^https:\/\/[^/]+/.exec(url)[0] + next;
      url = officialUrl_(next);
      continue;
    }
    if (code !== 200) throw new Error('Official GBFS returned HTTP ' + code);
    const raw = response.getContentText('UTF-8');
    const document = JSON.parse(raw);
    return {document: document, raw_json: raw, sha256_utf8: sha256_(raw),
      url: url, http_status: code, requested_at_utc: requested, received_at_utc: received};
  }
  throw new Error('Official redirect failed');
}

function validateStations_(document, label) {
  const stations = document && document.data && document.data.stations;
  if (!Array.isArray(stations) || stations.length === 0) throw new Error(label + ' is empty/malformed');
  const seen = new Set();
  stations.forEach(function (station) {
    // Reject numeric JSON identities rather than round IDs beyond 2^53.
    if (typeof station.station_id !== 'string' || !station.station_id || seen.has(station.station_id)) {
      throw new Error(label + ' has non-string, empty or duplicate station ID');
    }
    seen.add(station.station_id);
  });
  return stations.length;
}

function privateFolder_() {
  const id = PropertiesService.getScriptProperties().getProperty(BIKEFLOW.folderProperty);
  if (!id) throw new Error('Run setupCollector first');
  const folder = DriveApp.getFolderById(id);
  if (folder.getSharingAccess() !== DriveApp.Access.PRIVATE || folder.getEditors().length || folder.getViewers().length) {
    throw new Error('Collector folder must be private and unshared');
  }
  return folder;
}

function childFolder_(parent, name) {
  const matches = parent.getFoldersByName(name);
  return matches.hasNext() ? matches.next() : parent.createFolder(name);
}

function savePoll_(parent, record) {
  const day = childFolder_(parent, record.started_at_utc.slice(0, 10));
  const filename = record.started_at_utc.replace(/[-:.]/g, '') + '_' + record.poll_id + '.json.gz';
  const blob = Utilities.newBlob(JSON.stringify(record), 'application/json', filename.slice(0, -3));
  const file = day.createFile(Utilities.gzip(blob, filename));
  return {file_id: file.getId(), filename: filename, compressed_bytes: file.getSize()};
}

function stopCollector() {
  let count = 0;
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === BIKEFLOW.handler) { ScriptApp.deleteTrigger(trigger); count++; }
  });
  console.log(JSON.stringify({status: 'trigger_stopped',deleted_matching_triggers: count,data_deleted: false}));
}

function captureDivvySnapshot(event) {
  const started = new Date();
  if (started.getTime() >= Date.parse(BIKEFLOW.stopAtUtc)) {
    stopCollector();return {status: 'finished'};
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {status: 'overlap_skipped'};
  const props = PropertiesService.getScriptProperties();
  let folder;
  const record = {collector: BIKEFLOW.version,nominal_interval_minutes: 5,
    started_at_utc: started.toISOString(),poll_id: Utilities.getUuid(),
    invocation: event && event.triggerUid ? 'scheduled' : 'manual',
    scheduled_trigger_uid: event && event.triggerUid ? String(event.triggerUid) : null,
    status: 'error',full_snapshot: false,unchanged_inventory_suppressed: false,
    timing_policy: 'Actual provider/request/receipt times; missing intervals are not backfilled'};
  let saved;
  try {
    folder = privateFolder_();
    const day = record.started_at_utc.slice(0,10);
    const budget = JSON.parse(props.getProperty('BIKEFLOW_RUNTIME_BUDGET') || '{}');
    if (budget.day === day && budget.ms >= BIKEFLOW.runtimeBudgetMs) {
      stopCollector();throw new Error('Conservative daily runtime budget reached; stopped, no paid upgrade');
    }
    const discovery = fetchOfficial_(BIKEFLOW.discovery);
    const english = discovery.document.data && discovery.document.data.en;
    if (!english || !Array.isArray(english.feeds)) throw new Error('Unexpected official discovery schema');
    const urls = {};
    english.feeds.forEach(function (feed) { urls[feed.name] = feed.url; });
    const information = fetchOfficial_(urls.station_information);
    validateStations_(information.document, 'station_information');
    const status = fetchOfficial_(urls.station_status);
    record.station_count = validateStations_(status.document, 'station_status');
    record.sources = {discovery: discovery,station_information: information,station_status: status};
    record.provider_last_updated = status.document.last_updated;
    record.provider_ttl = status.document.ttl;
    record.stale_feed_over_5min = typeof status.document.last_updated === 'number' &&
      Date.parse(status.received_at_utc) / 1000 - status.document.last_updated > 300;
    // Store raw JSON text plus capture metadata, without duplicating parsed docs.
    Object.keys(record.sources).forEach(function (key) { delete record.sources[key].document; });
    record.status = 'ok';record.full_snapshot = true;
    record.finished_at_utc = new Date().toISOString();
    saved = savePoll_(folder, record);
    props.setProperty('BIKEFLOW_LAST_POLL', JSON.stringify({status:'ok',invocation:record.invocation,
      received_at_utc: status.received_at_utc,station_count:record.station_count,...saved}));
    console.log(JSON.stringify({status:'ok',invocation:record.invocation,...saved}));
    return {status:'ok',...saved};
  } catch (error) {
    record.status = 'error';record.full_snapshot = false;record.error = String(error);
    record.finished_at_utc = new Date().toISOString();
    // A completed success file is never followed by a duplicate error file if
    // only a convenience property/log update fails; the durable poll wins.
    if (folder && !saved) {
      try { saved = savePoll_(folder, record); } catch (storageError) {
        console.error('Unable to persist poll/error: ' + String(storageError));
      }
    }
    props.setProperty('BIKEFLOW_LAST_ERROR', JSON.stringify({at_utc:new Date().toISOString(),error:String(error)}));
    throw error;
  } finally {
    try { recordHealth_(record, saved); } catch (healthError) { console.error('Health index update failed: ' + String(healthError)); }
    const day = record.started_at_utc.slice(0,10);
    try {
      const budget = JSON.parse(props.getProperty('BIKEFLOW_RUNTIME_BUDGET') || '{}');
      props.setProperty('BIKEFLOW_RUNTIME_BUDGET',JSON.stringify({day:day,
        ms:(budget.day === day ? budget.ms : 0) + new Date().getTime() - started.getTime()}));
    } finally { lock.releaseLock(); }
  }
}

function setupCollector() {
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty(BIKEFLOW.folderProperty);
  if (!id) {
    const folder = DriveApp.createFolder('BikeFlowAI-Divvy-Full-Snapshots');
    id = folder.getId();props.setProperty(BIKEFLOW.folderProperty,id);
  }
  privateFolder_();
  const result = captureDivvySnapshot();
  console.log('Smoke poll saved. Run startCollector to enable five-minute collection.');
  console.log('Private folder: https://drive.google.com/drive/folders/' + id);
  return result;
}

function startCollector() {
  privateFolder_();
  if (Date.now() >= Date.parse(BIKEFLOW.stopAtUtc)) throw new Error('Project collection end already reached');
  const last = JSON.parse(PropertiesService.getScriptProperties().getProperty('BIKEFLOW_LAST_POLL') || '{}');
  if (last.status !== 'ok' || Date.now()-Date.parse(last.received_at_utc)>15*60*1000) {
    throw new Error('Run setupCollector and confirm a successful recent smoke capture first');
  }
  stopCollector();
  ScriptApp.newTrigger(BIKEFLOW.handler).timeBased().everyMinutes(5).create();
  console.log('Five-minute cloud trigger installed. Verify two scheduled runs before disabling Windows task.');
}

function collectorStatus() {
  const props = PropertiesService.getScriptProperties();
  const result = {collector:BIKEFLOW.version,nominal_interval_minutes:5,stop_at_utc:BIKEFLOW.stopAtUtc,
    matching_triggers:ScriptApp.getProjectTriggers().filter(function (t) { return t.getHandlerFunction()===BIKEFLOW.handler; }).length,
    folder_id:props.getProperty(BIKEFLOW.folderProperty),last_poll:JSON.parse(props.getProperty('BIKEFLOW_LAST_POLL') || '{}'),
    last_error:JSON.parse(props.getProperty('BIKEFLOW_LAST_ERROR') || '{}'),
    runtime_budget:JSON.parse(props.getProperty('BIKEFLOW_RUNTIME_BUDGET') || '{}')};
  console.log(JSON.stringify(result));return result;
}


/** Rolling metadata only: <=40 attempts/hour bucket, last 48 UTC hours.
 * Counts missing trigger slots independently of request failures. No Drive
 * folder scan, extra fetch, email, public endpoint or paid service is added.
 */
function recordHealth_(record, saved) {
  const props = PropertiesService.getScriptProperties();
  const prefix = 'BIKEFLOW_HEALTH_HOUR_';
  const key = prefix + record.started_at_utc.slice(0,13);
  const bucket = JSON.parse(props.getProperty(key) || '{"entries":[],"truncated":0}');
  const capture = record.sources && record.sources.station_status;
  const received = capture ? Date.parse(capture.received_at_utc) : Date.parse(record.started_at_utc);
  bucket.entries.push({t:Date.parse(record.started_at_utc),r:received,s:record.status,
    scheduled:record.invocation==='scheduled',n:record.station_count || null,
    provider:typeof record.provider_last_updated==='number' ? record.provider_last_updated : null,
    age:typeof record.provider_last_updated==='number' ? received/1000-record.provider_last_updated : null,
    saved:!!saved,b: saved ? saved.compressed_bytes : null});
  if (bucket.entries.length>40) { bucket.entries.shift();bucket.truncated++; }
  props.setProperty(key,JSON.stringify(bucket));
  const oldBefore=Date.now()-48*3600*1000;
  const all=props.getProperties();
  Object.keys(all).forEach(function(k){
    if(k.indexOf(prefix)===0 && Date.parse(k.slice(prefix.length)+':00:00Z')<oldBefore)props.deleteProperty(k);
  });
}

function healthPercentile_(values,p) {
  if(!values.length)return null;
  const a=values.slice().sort(function(x,y){return x-y;});
  const at=(a.length-1)*p,lo=Math.floor(at),hi=Math.ceil(at);
  return a[lo]+(a[hi]-a[lo])*(at-lo);
}

function summarizeHealth_(entries,nowMs,truncated) {
  const eligible=entries.filter(function(r){return r.t>=nowMs-24*3600*1000 && r.t<=nowMs;});
  const scheduled=eligible.filter(function(r){return r.scheduled;}).sort(function(a,b){return a.t-b.t;});
  if(!scheduled.length)return {status:'WAITING_FOR_SCHEDULED_HEALTH_RECORDS',scheduled_attempts:0,index_truncated_entries:truncated};
  const first=scheduled[0].t;
  const success=scheduled.filter(function(r){return r.s==='ok' && r.saved;});
  const slot=function(r){return Math.floor((r.t-first)/(5*60*1000)+.5);};
  const expected=Math.max(Math.floor((nowMs-first)/(5*60*1000))+1,Math.max.apply(null,scheduled.map(slot))+1);
  const occupied=new Set(scheduled.map(slot)),good=new Set(success.map(slot));
  const times=success.map(function(r){return r.r;}).sort(function(a,b){return a-b;});
  const intervals=[];for(let i=1;i<times.length;i++)intervals.push((times[i]-times[i-1])/1000);
  const boundaries=times.length?[(times[0]-first)/1000,(nowMs-times[times.length-1])/1000]:[(nowMs-first)/1000];
  const providers=success.filter(function(r){return r.provider!==null;}).map(function(r){return r.provider;});
  const counts=success.filter(function(r){return r.n!==null;}).map(function(r){return r.n;});
  const ages=success.filter(function(r){return r.age!==null;}).map(function(r){return r.age;});
  return {status:truncated?'PARTIAL_INDEX_TRUNCATED':'ROLLING_OBSERVED_WINDOW',
    collector:BIKEFLOW.version,nominal_interval_minutes:5,window_start_utc:new Date(first).toISOString(),window_end_utc:new Date(nowMs).toISOString(),
    window_basis:'First indexed scheduled attempt within last 24h; excludes earlier capture history',
    expected_poll_slots:expected,scheduled_attempts:scheduled.length,successful_polls:success.length,
    failed_attempts:scheduled.length-success.length,manual_attempts_excluded:eligible.length-scheduled.length,
    successful_slots:good.size,slots_without_success:expected-good.size,missing_attempt_slots:expected-occupied.size,
    extra_attempts_in_occupied_slot:scheduled.length-occupied.size,observed_slot_success_fraction:good.size/expected,
    median_interval_seconds:healthPercentile_(intervals,.5),p90_interval_seconds:healthPercentile_(intervals,.9),
    longest_gap_including_boundaries_seconds:Math.max.apply(null,intervals.concat(boundaries)),
    duplicate_capture_timestamps:times.length-new Set(times).size,repeated_provider_timestamps:providers.length-new Set(providers).size,
    station_count_min:counts.length?Math.min.apply(null,counts):null,station_count_max:counts.length?Math.max.apply(null,counts):null,
    feed_age_median_seconds:healthPercentile_(ages,.5),feed_age_p90_seconds:healthPercentile_(ages,.9),
    feed_age_max_seconds:ages.length?Math.max.apply(null,ages):null,stale_feed_polls_gt5min:ages.filter(function(v){return v>300;}).length,
    index_truncated_entries:truncated,limitation:'Quota/storage/termination may prevent an attempt/index entry; expected missing slots remain missing, never empty inventory'};
}

function collectorHealth() {
  const all=PropertiesService.getScriptProperties().getProperties();const entries=[];let truncated=0;
  Object.keys(all).forEach(function(k){
    if(k.indexOf('BIKEFLOW_HEALTH_HOUR_')===0){const bucket=JSON.parse(all[k]);entries.push.apply(entries,bucket.entries);truncated+=bucket.truncated || 0;}
  });
  const result=summarizeHealth_(entries,Date.now(),truncated);
  console.log(JSON.stringify(result));return result;
}
