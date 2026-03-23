FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 7070
CMD ["uvicorn", "argus.outputs.dashboard.app:app", "--host", "0.0.0.0", "--port", "7070"]
