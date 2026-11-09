"""Repeatable synthetic replay smoke benchmark, not model-quality evaluation.

Run from the project root after installing requirements.txt. The generated data
is temporary; only aggregate timing / server-error counts are written.
"""
import json
import logging
import statistics
import random
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'tests'))

from fastapi.testclient import TestClient
from backend.main import app
from test_app_providers import ReplayProviderTests


def main():
    fixture = ReplayProviderTests()
    fixture.setUp()
    logger = logging.getLogger('bikeflow.requests')
    disabled_before = logger.disabled
    try:
        with patch('backend.main.Providers', return_value=fixture.provider), patch.dict('os.environ', {'BIKEFLOW_LIVE':'0'}):
            with TestClient(app) as client:
                body = dict(mode='replay', origin='chicago:14', destination='chicago:21',
                            historical_timestamp=fixture.q.isoformat(), departure_time=fixture.q.isoformat(),
                            walk_limit_minutes=10, method='B3')
                client.post('/plan', json=body).raise_for_status()
                durations, errors = [], 0
                logger.disabled = True
                rng = random.Random(7)
                ids = [s['id'] for s in fixture.stations]
                for i in range(1000):
                    if i >= 500:
                        origin, destination = rng.sample(ids, 2)
                        body.update(origin=origin, destination=destination, walk_limit_minutes=rng.choice([0,5,10]),
                                    method=rng.choice(['B1','B2','B3']))
                    started = time.perf_counter()
                    response = client.post('/plan', json=body)
                    if i < 500:
                        durations.append((time.perf_counter()-started)*1000)
                    errors += response.status_code >= 500
                    if response.status_code != 200:
                        raise RuntimeError(response.text)
                report = dict(scope='Synthetic Parquet replay with real B2 serving, in-process TestClient; not team-model or browser performance',
                              cached_requests=500, cached_p95_ms=round(statistics.quantiles(durations,n=100)[94],2),
                              valid_requests=1000, server_errors=errors, seed=7)
    finally:
        logger.disabled = disabled_before
        fixture.tearDown()
    output = PROJECT / 'reports/app_demo/synthetic_smoke.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
