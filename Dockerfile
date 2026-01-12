FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a directory for downloads inside the container
RUN mkdir /downloads

# Run the app
CMD ["python", "app.py"]