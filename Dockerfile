# Receipts judge Docker test:
#   docker build -t oah-submission .
#   docker run --rm -p 8000:8000 --env-file .env oah-submission
# Keyless judge test (step 9):
#   docker run --rm -p 8000:8000 -e SAMPLE_MODE=true oah-submission
# then POST /run with an input_examples/*.json payload.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV SAMPLE_MODE=true
EXPOSE 8000
CMD ["python", "run.py", "--serve"]
