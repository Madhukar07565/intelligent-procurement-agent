# Procurement Agent web app (Streamlit). Built for linux/amd64 by the CDK stack in /workshop/infra.
FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime dependencies only (tests and their tools are not installed).
RUN pip install "boto3==1.44.7" "streamlit==1.67.0" "fpdf2==2.9.0"

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --chown=app:app app.py docker-entrypoint.py ./
COPY --chown=app:app .streamlit ./.streamlit
COPY --chown=app:app src ./src
COPY --chown=app:app data/quotes.json ./data/quotes.json

USER app
EXPOSE 8501
ENTRYPOINT ["python", "docker-entrypoint.py"]
