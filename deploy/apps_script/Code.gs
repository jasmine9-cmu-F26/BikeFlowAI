/** BikeFlow AI: private full Divvy polls on Google Apps Script free quotas.
 * No billing API, public endpoint, paid subscription or raw-data Git commit.
 * Five-minute triggers are best-effort; actual source/request/receipt times win.
 */
const BIKEFLOW = Object.freeze({
  version: 'apps-script-v1',
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
