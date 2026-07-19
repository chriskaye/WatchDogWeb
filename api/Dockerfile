FROM python:3.12

WORKDIR /app

# Install OS security patches
RUN apt-get update && apt-get upgrade -y

# Copy dependency list
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
