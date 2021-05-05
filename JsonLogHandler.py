import logging, os, requests

class JsonLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        url = os.getenv('EPISODE_LOG_URL')
        return requests.post(url, log_entry, headers={"Content-type": "application/json"}).content