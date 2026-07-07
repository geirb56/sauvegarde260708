FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r /app/requirements.txt
CMD ["celery", "-A", "tasks.sync_tasks", "worker", "--loglevel=info", "-Q", "SYNC_USER,FETCH_NEW_ACTIVITIES,PROCESS_ACTIVITY,COMPUTE_METRICS"]
