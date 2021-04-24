FROM python:3.9

WORKDIR /vaccinewatcher
COPY . . 

# Install dependencies
COPY requirements.txt .
RUN pip3 install -r requirements.txt 

# Run application
CMD [ "python", "vaccinewatcher/watcher.py" ]

