export type Mode = 'fixture'|'replay'|'live';
export type Method = 'B1'|'B2'|'B3'|'RL';
export type Point = {lat:number; lon:number};
export type Endpoint = string | Point;
export type Station = Point & {id:string; name:string; bikes:number; docks:number; pickup:boolean; return:boolean; data_age_seconds:number; forecast:Record<string,{p_bike:number|null;p_dock:number|null}>};
export type Snapshot = {mode:Mode; decision_time:string; stations:Station[]; stale:boolean; active_method:string; model_version:string|null; warnings:string[]};
export type Health = {status:string; active_method:string; replay_data_ready:boolean; rl_ready:boolean; live_cache_ready:boolean};
export type Stop = Point & {id:string; name:string; walk_minutes:number; probability:number; bikes:number; docks:number; horizon_minutes:number; estimated_arrival_time:string; effective_prediction_time:string; data_age_seconds:number};
export type Route = {pickup:Stop|null; dropoff:Stop; wait_minutes:number; ride_minutes:number; ride_method:string; total_minutes:number};
export type Plan = {status:string; requested_method:Method; actual_method:string; mode:Mode; primary:Route|null; backups:Route[]; warnings:string[]; no_plan_reason:string|null; request_id:string; decision_time:string; latency_ms:number; model_version:string|null; data_age_seconds:number|null; backup_semantics?:string};
export type Request = {origin:Endpoint; destination:Endpoint; departure_time:string; historical_timestamp?:string; walk_limit_minutes:number; mode:Mode; method:Method; scenario:string};
export async function api<T>(path:string, body?:unknown, signal?:AbortSignal):Promise<T>{
  const res=await fetch('/api'+path, {method:body?'POST':'GET', headers:body?{'Content-Type':'application/json'}:undefined, body:body?JSON.stringify(body):undefined, signal});
  const data=await res.json();
  if(!res.ok){const d=data.detail;throw new Error(Array.isArray(d)?d.map(e=>`${e.field}: ${e.error}`).join('; '):d?.error||'The service could not complete this request.');}
  return data;
}
export function clock(value:string){return new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/Chicago'}).format(new Date(value));}
export function chicagoNow(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ','T');}
// datetime-local values are Chicago wall time. The demo historical window uses CDT;
// live departure is emitted as an absolute instant instead of assuming a DST offset.
export function historical(value:string){return value+':00-05:00';}
