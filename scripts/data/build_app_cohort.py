"""Audit/freeze the deployable cohort separately from the original 42 stations.

Selection uses training-qualified stations plus fixed external live identity
evidence, never held-out labels or model results. No raw data is downloaded.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from bikeflow_data.temporal import norm_name


def read_csv(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def select_app_stations(selected,live):
    qualified={r['station_id']:r for r in selected}
    if len(qualified)!=len(selected):raise ValueError('Duplicate training-qualified ID')
    result=[]
    for row in live:
        sid=row['station_id']
        if sid not in qualified or row['match_status']!='exact_name_geo_unique':continue
        if not row.get('current_station_id') or norm_name(row['historical_name'])!=norm_name(row['current_name']) or float(row['distance_m'])>50:
            raise ValueError('Invalid confirmed identity evidence')
        result.append(dict(station_id=sid,historical_station_id=qualified[sid]['historical_station_id'],
            historical_name=qualified[sid]['name'],historical_lat=qualified[sid]['train_lat'],historical_lon=qualified[sid]['train_lon'],
            current_station_id=row['current_station_id'],current_name=row['current_name'],current_short_name=row['current_short_name'],
            distance_m=row['distance_m'],selection_rule='training_qualified_intersect_fixed_unique_live_name_geo',
            metadata_use='current_identity_for_serving_only_not_historical_features'))
    if not result or len({r['station_id'] for r in result})!=len(result) or len({r['current_station_id'] for r in result})!=len(result):
        raise ValueError('App cohort must have unique historical and live IDs')
    return sorted(result,key=lambda r:r['station_id'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--base-reports',type=Path,default=Path('reports/chicago_historical_audit'))
    p.add_argument('--base-manifests',type=Path,default=Path('data/manifests/chicago'))
    args=p.parse_args();base=args.base_reports;maps=args.base_manifests
    out=base/'app32';out.mkdir(parents=True,exist_ok=True)
    appmaps=maps/'app32';appmaps.mkdir(parents=True,exist_ok=True)
    original=json.loads((base/'audit_summary.json').read_text())
    chosen=select_app_stations(read_csv(maps/'selected_stations.csv'),read_csv(base/'live_station_overlap.csv'))
    if len(chosen)!=32:raise ValueError('Version 1 expects 32 app stations; new evidence needs a new protocol version')
    cohort=maps/'app_stations.csv'
    with cohort.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(chosen[0]));w.writeheader();w.writerows(chosen)
    scriptroot=Path(__file__).parent
    for name,options in [('audit_chicago_historical.py',['--cohort-manifest',str(cohort)]),('audit_chicago_trips.py',[])]:
        subprocess.run([sys.executable,str(scriptroot/name),'--data-root',str(args.data_root),'--reports',str(out),'--manifests',str(appmaps),*options],check=True)
    summary=json.loads((out/'audit_summary.json').read_text());trip=json.loads((out/'trip_overlap.json').read_text())
    if summary['decision']!='PASS_BOUNDED_SNAPSHOT_FEASIBILITY' or summary['stations_selected_from_training']!=32:
        raise ValueError('App source/cohort feasibility failed; do not freeze as passed')
    splitrows=read_csv(appmaps/'split_manifest.csv')
    for row in splitrows:row['status']='frozen_app_data_protocol_v1_model_tables_pending'
    with (appmaps/'split_manifest.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(splitrows[0]));writer.writeheader();writer.writerows(splitrows)
    snapshot_report=out/'data_audit.md'
    snapshot_report.write_text(snapshot_report.read_text(encoding='utf-8').replace(
        'Final station/rule/split approval, feature generation, historical/live semantics, model evaluation, and old-to-2026 domain shift remain separate tasks.',
        'The fixed app cohort, exact splits and timing rules are frozen in data_protocol.json version 1. Feature generation, historical/live feature semantics, model evaluation, and old-to-2026 domain shift remain separate tasks.'),encoding='utf-8')
    protocol=dict(version=1,status='frozen_data_protocol_model_tables_pending',training_ready=False,
        scope='32 fixed identity-matched stations for primary app/model/replay cohort; original 42-station feasibility audit remains separate',
        historical_dataset='eq45-8inv',start_local=original['requested_start_local'],end_local_exclusive=original['requested_end_local_exclusive'],
        timezone='America/Chicago',station_count=32,cohort_manifest='data/manifests/chicago/app_stations.csv',cohort_sha256=digest(cohort),
        selection='Training-qualified cohort intersect fixed captured 2026 identity evidence; no label/test/model performance filters',
        live_identity_evidence_capture_utc=original['current_2026_mapping_capture_utc'],
        live_identity_evidence_sha256=digest(base/'live_station_overlap.csv'),
        horizons_minutes=[10,20,30,40,50,60],label_matching=dict(tolerance_seconds=300,method='nearest valid strictly after request, ties earlier, same split, reject >50m relocation',missing='exclude, never zero or arbitrary forward fill'),
        chronological_splits=original['splits'],nominal_split_proportions=[.6,.15,.1,.15],actual_calendar_weeks_before_purge=[10,2,2,3],purge_before_later_splits_minutes=60,
        causal_features=dict(rule='latest recorded valid observation at or before decision time only',max_age_seconds=900,
            missing_or_stale='exclude request from this replay protocol; do not read future observations',
            historical_publication_latency='unmeasured; source recorded timestamps are an explicit availability assumption'),
        target_access='Future observations may be read only by offline labels/outcome evaluation; unavailable to model/planner input or action selection',
        od_estimation=dict(split='train only, both trip times in train',duration_seconds=[60,21600],minimum_pair_rides=20,unsupported_pairs='geometric fallback required'),
        historical_status='Broad In Service flag; do not invent installed/renting/returning/disabled fields',
        live_status='Check installed/renting/returning per current official GBFS; do not infer operability from identity mapping alone',
        limitations=['10-minute quantized observations, not exact continuous-time truth','Completed rides omit unmet demand','2021 summer to 2026 domain/season shift needs current-data validation','Frozen cohort identity does not prove uninterrupted operation or current station service'],
        source_manifest_sha256=summary['download_manifest_sha256'],snapshot_auditor_sha256=summary['audit_script_sha256'],trip_auditor_sha256=trip['script_sha256'],shared_temporal_sha256=summary['shared_temporal_sha256'],
        builder_sha256=digest(Path(__file__)),completed_checks=dict(snapshot_audit='PASS_BOUNDED_SNAPSHOT_FEASIBILITY',trip_audit='completed',full_replay_implemented=False,feature_label_table_certified=False))
    (appmaps/'data_protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    balance=next(r for r in read_csv(out/'class_balance.csv') if r['group']=='training_selected' and r['split']=='sample')
    labels=[r for r in read_csv(out/'label_retention.csv') if r['group']=='training_selected' and r['split']=='sample']
    context=trip['both_selected_stations_causal_context_at_departure']/trip['both_selected_endpoints']
    text=f'''# App cohort: 32 stations, protocol version 1

**PASS_BOUNDED_SNAPSHOT_FEASIBILITY** for the fixed 32-station cohort. This is separate from the original 42-station audit. Training tables and a full replay evaluator are not implemented/certified.

| Check | Result |
|---|---:|
| Historical sample | 2021-05-03 to 2021-08-30 (exclusive), 17 weeks |
| App stations | 32 distinct historical IDs and 32 distinct matched live IDs |
| Lowest per-station valid coverage across splits | {summary['minimum_selected_station_valid_coverage_across_splits']:.4%} |
| Lowest aggregated label retention across splits/horizons | {summary['minimum_selected_label_retention_across_splits_horizons']:.4%} |
| Bike / dock unavailable, selected sample | {float(balance['bike_unavailable_rate']):.2%} / {float(balance['dock_unavailable_rate']):.2%} |
| Both endpoints mapped among trips naming this app cohort | {trip['mapping_success_among_named_cohort']:.2%} |
| Mapped app trips with pickup/return observations within +/-5min | {trip['selected_trip_observation_support']:.2%} |
| Mapped app trips with both station contexts as-of departure, <=15min old | {context:.2%} |
| Eligible training-only OD rides | {trip['eligible_training_OD_rides']:,} |
| Observed OD pairs / pairs with >=20 training rides | {trip['observed_OD_pairs']} / {trip['OD_pairs_20plus']} |

| Horizon minutes | Sample label retention |
|---:|---:|
'''
    text+='\n'.join(f"| {r['horizon_minutes']} | {float(r['retention']):.4%} |" for r in labels)
    text+='''

The mapping denominator above is restricted to the 32 app stations; the snapshot audit retains all 50 candidate diagnostics and marks the fixed 32 as its selected report cohort. No held-out label or performance metric selects/removes a station. The 2026 identity filter defines a deployable subset and must not be described as unbiased full-network performance.

Station IDs are strings. Current identity is serving/mapping evidence only; historical features use historical observations. Known broad historical closure is an unavailable label; current renting/returning/installed flags are checked separately in live serving.

Feature context uses the latest valid recorded snapshot <= decision time with maximum age 900 seconds. Future observations are permitted only for offline target labels/outcome scoring. Missing/stale features or outcomes exclude the request; exact source publication latency is unmeasured. The as-of support check is not a trained model, causal stock-before-checkout proof, or implemented full replay.

The frozen split dates are in [split_manifest.csv](../../../data/manifests/chicago/app32/split_manifest.csv). Whole-week rounding yields 10/2/2/3 calendar weeks with 60-minute separation before later splits, rather than exact percentage durations.

See [snapshot audit](data_audit.md), [trip/OD audit](trip_overlap.md), [protocol](../../../data/manifests/chicago/app32/data_protocol.json), and [app stations](../../../data/manifests/chicago/app_stations.csv). Raw data stays outside Git. Source terms and the required City notice remain applicable.
'''
    (out/'README.md').write_text(text,encoding='utf-8')
    (appmaps/'README.md').write_text('''# Fixed 32-station app cohort

`data_protocol.json` freezes version 1 cohort, exact split dates, horizons, matching, causal feature freshness and training-only OD policy. `selected_stations.csv` contains the same 32 historical IDs as [../app_stations.csv](../app_stations.csv). Original 42-station manifests remain one directory above and are not overwritten.

These are audited data-protocol artifacts; model-ready tables and a full replay evaluator remain pending. See [32-station report](../../../../reports/chicago_historical_audit/app32/README.md).
''')
    print(json.dumps(dict(app_station_count=32,snapshot_decision=summary['decision'],mapping=trip['mapping_success_among_named_cohort'],trip_observation_support=trip['selected_trip_observation_support'],causal_context_support=context,training_od_rides=trip['eligible_training_OD_rides'],od_pairs_20plus=trip['OD_pairs_20plus']),indent=2))


if __name__=='__main__':main()
