FROM python:3.11-slim
WORKDIR /app
COPY ./api /app
RUN pip install --no-cache-dir -r /app/requirements.txt
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
