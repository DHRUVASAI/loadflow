FROM python:3.10-slim

# Create a non-root user (required by Hugging Face Spaces)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app with correct permissions
COPY --chown=user . .

# Hugging Face Spaces require running on port 7860
ENV PORT=7860
EXPOSE 7860

# Run with Gunicorn. 
# HF Spaces will map this port 7860 to public HTTPS URLs automatically
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:7860", "--worker-class", "gthread", "--threads", "4", "--timeout", "120"]
