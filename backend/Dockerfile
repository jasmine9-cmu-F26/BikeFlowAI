FROM python:3.14-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY scripts/data/requirements.txt scripts/data/requirements.txt
COPY scripts/model/requirements.txt scripts/model/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY scripts/model scripts/model
COPY data/manifests/chicago/app_stations.csv data/manifests/chicago/app_stations.csv
COPY reports/final_pipeline_audit/features/feature_schema.json reports/final_pipeline_audit/features/feature_schema.json
COPY reports/final_pipeline_audit/trip_od/planner_od.csv reports/final_pipeline_audit/trip_od/planner_od.csv
ENV BIKEFLOW_DATA_ROOT=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
