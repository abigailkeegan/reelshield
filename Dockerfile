FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformer model so the first /api/discover
# call with a mood phrase doesn't pay the 80 MB download cost at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Copy backend and frontend
COPY backend/ backend/
COPY frontend/ frontend/

# Create data directory for SQLite cache
RUN mkdir -p /data

ENV TMDB_API_KEY=""
ENV GEMINI_API_KEY=""
ENV OMDB_API_KEY=""

EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--timeout", "120", "backend.app:app"]
